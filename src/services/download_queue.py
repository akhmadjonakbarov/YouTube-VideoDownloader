"""The download queue: runs up to N videos at once, the rest wait their turn.

Each queued link is a QueueItem made of one or more Tasks. A Task is one yt-dlp run:
a single video, or (for playlists) one video of the playlist, so several videos of
the same playlist can download at the same time. If a site gives no separate link
per playlist video, the whole playlist is one Task that yt-dlp works through in order.

Everything here runs on the UI (main) thread. Tasks run in worker threads started by
the `spawn` callback; their progress and results come back through on_progress /
on_result / on_error (the app forwards them via its event queue). This keeps the
logic free of Tk, so it is easy to test.
"""
import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from models.media import DownloadResult, MediaInfo, ProgressInfo, QualityOption
from services.video_downloader import DOWNLOAD_STAGES, STAGE_SAVED, DownloadJob

# Item states
QUEUED = "queued"
RUNNING = "running"
PAUSING = "pausing"      # asked to pause; the workers are stopping
PAUSED = "paused"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
FINAL = (COMPLETED, FAILED, CANCELLED)

# Task states
TASK_WAITING = "waiting"
TASK_RUNNING = "running"
TASK_DONE = "done"
TASK_FAILED = "failed"

# Auto-pause: a download whose speed stays below SLOW_BYTES_PER_SEC for STALL_SECONDS
# counts as stalled. Everything pauses as soon as the network is gone.
SLOW_BYTES_PER_SEC = 16 * 1024
STALL_SECONDS = 25
RESUME_DELAY = {"network": 3, "slow": 10}  # wait a little after the connection returns
MAX_AUTO_RESUMES = 5                       # then stop retrying and ask the user

DEFAULT_CONCURRENCY = 2
CONCURRENCY_CHOICES = (1, 2, 3, 4, 5)
NO_VIDEOS_SAVED = "None of the selected videos could be downloaded."

# States of one video inside a playlist download.
ENTRY_WAITING = "waiting"
ENTRY_ACTIVE = "active"   # started (downloading, processing, or stopped part-way)
ENTRY_DONE = "done"
ENTRY_FAILED = "failed"   # unavailable, private or failed


@dataclass(eq=False)
class EntryState:
    """One video of a playlist download, for the playlist detail screen."""
    index: int                 # position in the playlist
    title: str
    duration: float | None = None
    url: str | None = None     # its own link, when the site gives one
    state: str = ENTRY_WAITING
    running: bool = False      # being worked on right now
    stage: str | None = None
    fraction: float = 0.0
    speed: float | None = None
    eta: float | None = None
    error: str | None = None


@dataclass
class JobSpec:
    """What one Task should download (passed to the job factory)."""
    url: str
    playlist: bool                 # let yt-dlp walk a playlist (the one-by-one fallback)
    items: list[int] | None = None
    total: int = 1
    folder: str | None = None      # playlist folder for a single playlist video
    index: int | None = None       # its position, used in the file name


@dataclass(eq=False)
class Task:
    id: int
    item: "QueueItem"
    job: DownloadJob
    entry: EntryState | None = None  # the playlist video this task downloads
    state: str = TASK_WAITING
    downloading: bool = False        # in a download stage (for stall detection)
    speed: float | None = None
    result: DownloadResult | None = None
    error: str | None = None


@dataclass(eq=False)
class QueueItem:
    id: int
    media: MediaInfo
    option: QualityOption
    items: list[int] | None
    total: int
    tasks: list[Task] = field(default_factory=list)
    status: str = QUEUED
    pause_reason: str | None = None   # "user" / "network" / "slow" / "failing"
    cancelling: bool = False
    progress: ProgressInfo | None = None
    fraction: float = 0.0             # overall progress (whole playlist)
    item_fraction: float = 0.0        # progress of the current file
    result: DownloadResult | None = None
    error: str | None = None
    paused_at: float = 0.0
    last_good_progress: float = 0.0
    auto_resumes: int = 0
    held_slots: int = 0               # slots kept while auto-paused (see running_count)
    entries: list[EntryState] = field(default_factory=list)  # playlists only, in playlist order

    @property
    def title(self) -> str:
        return self.media.title

    @property
    def is_active(self) -> bool:
        return self.status not in FINAL

    @property
    def is_playlist(self) -> bool:
        return self.media.is_playlist

    @property
    def per_video(self) -> bool:
        """A playlist downloaded as separate videos (several at once)."""
        return any(t.entry is not None for t in self.tasks)

    @property
    def job(self) -> DownloadJob:
        return self.tasks[0].job

    @property
    def running_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.state == TASK_RUNNING]

    @property
    def downloading_stage(self) -> bool:
        return any(t.downloading for t in self.running_tasks)

    @property
    def speed(self) -> float:
        return sum(t.speed or 0 for t in self.running_tasks)

    @property
    def completed_files(self) -> set[str]:
        files: set[str] = set()
        for t in self.tasks:
            files |= t.job.completed_files
        return files

    @property
    def saved_count(self) -> int:
        if self.entries:
            return sum(1 for e in self.entries if e.state == ENTRY_DONE)
        return sum(1 for t in self.tasks if t.state == TASK_DONE)

    def entry(self, index: int | None) -> EntryState | None:
        return next((e for e in self.entries if e.index == index), None) if index is not None else None

    def entry_counts(self) -> dict[str, int]:
        counts = {ENTRY_WAITING: 0, ENTRY_ACTIVE: 0, ENTRY_DONE: 0, ENTRY_FAILED: 0}
        for e in self.entries:
            if e.state in (ENTRY_DONE, ENTRY_FAILED):
                counts[e.state] += 1
            else:
                counts[ENTRY_ACTIVE if e.running else ENTRY_WAITING] += 1
        return counts


# job_factory(task_id, spec, option) -> DownloadJob
JobFactory = Callable[[int, JobSpec, QualityOption], DownloadJob]
# on_event(kind, item): kinds are "added", "updated", "progress", "saved", "removed",
# "completed", "failed", "cancelled", "auto_paused", "auto_resumed"
EventHandler = Callable[[str, QueueItem], None]


class DownloadQueue:
    def __init__(self, job_factory: JobFactory, spawn: Callable[[Task], None], on_event: EventHandler,
                 max_concurrent: int = DEFAULT_CONCURRENCY, clock: Callable[[], float] = time.monotonic):
        self.job_factory = job_factory
        self.spawn = spawn
        self.on_event = on_event
        self.max_concurrent = max_concurrent
        self.clock = clock
        self.items: list[QueueItem] = []
        self.tasks: dict[int, Task] = {}
        self.online = True
        self._ids = itertools.count(1)
        self._task_ids = itertools.count(1)

    # ------------------------------------------------------------------ queries

    def get(self, item_id: int) -> QueueItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    def get_task(self, task_id: int) -> Task | None:
        return self.tasks.get(task_id)

    def running_count(self) -> int:
        """Busy slots: running tasks, plus the slots of downloads auto-paused by a
        network problem, so those continue before anything that hasn't started yet."""
        return sum(len(i.running_tasks) for i in self.items) + sum(
            i.held_slots for i in self.items if i.status == PAUSED and i.pause_reason in RESUME_DELAY)

    def active_items(self) -> list[QueueItem]:
        return [i for i in self.items if i.is_active]

    def has_active(self) -> bool:
        return any(i.is_active for i in self.items)

    def find_duplicate(self, media: MediaInfo, option: QualityOption, items: list[int] | None) -> QueueItem | None:
        return next((i for i in self.items if i.is_active and i.media.url == media.url
                     and i.option == option and i.items == items), None)

    # ----------------------------------------------------------------- actions

    def add(self, media: MediaInfo, option: QualityOption, items: list[int] | None) -> QueueItem:
        total = (len(items) if items else len(media.entries)) if media.is_playlist else 1
        item = QueueItem(next(self._ids), media, option, items, total)
        if media.is_playlist:
            wanted = set(items) if items else None
            item.entries = [EntryState(e.index, e.title, e.duration, e.url)
                            for e in sorted(media.entries, key=lambda e: e.index)
                            if wanted is None or e.index in wanted]

        if item.entries and all(e.url for e in item.entries):
            for entry in item.entries:  # one task per video: several can run at once
                spec = JobSpec(entry.url, playlist=False, folder=media.title, index=entry.index)
                self._add_task(item, spec, entry)
        else:
            self._add_task(item, JobSpec(media.url, media.is_playlist, items, total))
        self.items.append(item)
        self.on_event("added", item)
        self.schedule()
        return item

    def _add_task(self, item: QueueItem, spec: JobSpec, entry: EntryState | None = None) -> None:
        task_id = next(self._task_ids)
        task = Task(task_id, item, self.job_factory(task_id, spec, item.option), entry)
        item.tasks.append(task)
        self.tasks[task_id] = task

    def schedule(self) -> None:
        """Start waiting tasks, oldest item first, while there are free slots (not while offline)."""
        if not self.online:
            return
        for item in self.items:
            if item.status not in (QUEUED, RUNNING) or item.cancelling:
                continue
            for task in item.tasks:
                if self.running_count() >= self.max_concurrent:
                    return
                if task.state == TASK_WAITING:
                    self._start(task)

    def _start(self, task: Task) -> None:
        item = task.item
        task.state = TASK_RUNNING
        task.downloading = False
        task.speed = None
        task.job.pause_event.clear()
        if task.entry is not None:
            task.entry.running = True
        if item.status == QUEUED:
            item.status = RUNNING
            item.pause_reason = None
            item.last_good_progress = self.clock()
        self.spawn(task)
        self.on_event("updated", item)

    def pause(self, item: QueueItem, reason: str = "user") -> None:
        if item.status == RUNNING:
            item.status = PAUSING
            item.pause_reason = reason
            item.paused_at = self.clock()
            running = item.running_tasks
            item.held_slots = len(running) if reason in RESUME_DELAY else 0
            for task in running:
                task.job.pause_event.set()
            self.on_event("updated", item)
            self._settle(item)
        elif item.status == QUEUED:
            item.status = PAUSED
            item.pause_reason = "user"
            item.held_slots = 0
            self.on_event("updated", item)

    def resume(self, item: QueueItem, auto: bool = False) -> None:
        if item.status != PAUSED:
            return
        if not auto:
            item.auto_resumes = 0
        item.status = QUEUED
        item.pause_reason = None
        item.held_slots = 0
        self.on_event("updated", item)
        self.schedule()

    def cancel(self, item: QueueItem) -> None:
        if item.status in (RUNNING, PAUSING):
            item.cancelling = True
            for task in item.tasks:
                task.job.cancel_event.set()
            self.on_event("updated", item)
            self._settle(item)
        elif item.status in (QUEUED, PAUSED):
            item.status = CANCELLED
            self._stop_entries(item)
            self.on_event("cancelled", item)
            self.schedule()

    def remove(self, item: QueueItem) -> None:
        if item.status in FINAL and item in self.items:
            self.items.remove(item)
            for task in item.tasks:
                self.tasks.pop(task.id, None)
            self.on_event("removed", item)

    def clear_finished(self) -> None:
        for item in [i for i in self.items if i.status in FINAL]:
            self.remove(item)

    def set_max_concurrent(self, n: int) -> None:
        self.max_concurrent = max(1, n)
        self.schedule()

    def _auto_pause(self, item: QueueItem, reason: str) -> None:
        if item.status == RUNNING and item.pause_reason is None:
            self.pause(item, reason)
            self.on_event("auto_paused", item)

    # ---------------------------------------------------- reports from workers

    def on_progress(self, task_id: int, p: ProgressInfo) -> None:
        task = self.get_task(task_id)
        if task is None or task.state != TASK_RUNNING:
            return
        item = task.item
        now = self.clock()
        if p.stage in DOWNLOAD_STAGES:
            if not task.downloading:
                task.downloading = True
                item.last_good_progress = now
            task.speed = p.speed
            if p.speed and p.speed >= SLOW_BYTES_PER_SEC:
                item.last_good_progress = now
                item.auto_resumes = 0
        else:
            task.downloading = False
            task.speed = None

        if task.entry is not None:
            tracked = self._update_entry(item, task.entry, p, in_order=False)
        else:
            tracked = self._update_entry(item, item.entry(p.playlist_index), p, in_order=True)
        if p.stage == STAGE_SAVED:
            self.on_event("saved", item)
        if item.status != RUNNING:
            if tracked:
                self.on_event("progress", item)  # a video finished while pausing
            return

        item.progress = p
        if p.fraction is not None:
            item.item_fraction = max(0.0, min(1.0, p.fraction))
        if tracked:
            item.fraction = self._entries_fraction(item)
        elif item.is_playlist:
            saved = p.stage == STAGE_SAVED
            done = (p.item_number or 1) - (0 if saved else 1)
            item.fraction = min(1.0, (done + (0 if saved else item.item_fraction)) / max(1, item.total))
        else:
            item.fraction = item.item_fraction
        self.on_event("progress", item)

    def on_result(self, task_id: int, result: DownloadResult) -> None:
        task = self.get_task(task_id)
        if task is None:
            return
        item = task.item
        task.result = result
        cancelled = result.cancelled or item.cancelling or task.job.cancel_event.is_set()
        self._stop_task(task)
        if cancelled:
            task.state = TASK_WAITING
        elif result.paused:
            task.state = TASK_WAITING  # run the same job again later: it continues the .part file
            if item.status == RUNNING:  # yt-dlp hit a network error on its own
                reason = "network" if result.network_error else "user"
                self.pause(item, reason)
                if reason in RESUME_DELAY:
                    item.held_slots += 1  # this task's slot too
                    self.on_event("auto_paused", item)
        else:
            task.state = TASK_DONE
            if task.entry is not None and task.entry.state != ENTRY_DONE:
                self._set_entry(task.entry, ENTRY_DONE)
        self._settle(item)
        self.schedule()
        self._settle(item)

    def on_error(self, task_id: int, message: str) -> None:
        task = self.get_task(task_id)
        if task is None:
            return
        item = task.item
        self._stop_task(task)
        task.state = TASK_FAILED
        task.error = message
        if task.entry is not None:
            self._set_entry(task.entry, ENTRY_FAILED)
            task.entry.error = message
            self.on_event("progress", item)
        else:
            item.error = message
        self._settle(item)
        self.schedule()
        self._settle(item)

    def _stop_task(self, task: Task) -> None:
        task.downloading = False
        task.speed = None
        if task.entry is not None:
            task.entry.running = False
            task.entry.speed = task.entry.eta = None
        else:
            for e in task.item.entries:  # the one-by-one fallback: its current video stopped
                e.running = False

    def _settle(self, item: QueueItem) -> None:
        """Work out the item's status from its tasks."""
        if item.running_tasks:
            if item.status == QUEUED:
                item.status = RUNNING
            return
        if item.cancelling:
            item.status = CANCELLED
            item.cancelling = False
            self._stop_entries(item)
            self.on_event("cancelled", item)
        elif item.status == PAUSING:
            item.status = PAUSED
            self.on_event("updated", item)
        elif item.status in (QUEUED, RUNNING):
            if any(t.state == TASK_WAITING for t in item.tasks):
                if item.status == RUNNING:
                    item.status = QUEUED  # waiting for a free slot (the limit was lowered)
                    self.on_event("updated", item)
            else:
                self._finish(item)

    def _finish(self, item: QueueItem) -> None:
        if item.per_video:
            saved = item.saved_count
        else:
            saved = sum(t.result.completed for t in item.tasks if t.state == TASK_DONE and t.result)
        if saved == 0:
            item.status = FAILED
            # e.g. every video failed the same way: show that reason
            item.error = item.error or next((t.error for t in item.tasks if t.error), None) or NO_VIDEOS_SAVED
            self._stop_entries(item)
            self.on_event("failed", item)
            return
        item.status = COMPLETED
        item.fraction = 1.0
        item.result = DownloadResult(saved, item.total)
        for e in item.entries:  # whatever wasn't saved was unavailable
            if e.state != ENTRY_DONE:
                self._set_entry(e, ENTRY_FAILED)
        self.on_event("completed", item)

    # ------------------------------------------------------- playlist videos

    @staticmethod
    def _set_entry(entry: EntryState, state: str) -> None:
        entry.state = state
        entry.running = False
        entry.speed = entry.eta = None
        if state == ENTRY_DONE:
            entry.fraction, entry.stage = 1.0, STAGE_SAVED

    @staticmethod
    def _stop_entries(item: QueueItem) -> None:
        for e in item.entries:
            e.running = False
            e.speed = e.eta = None

    def _update_entry(self, item: QueueItem, entry: EntryState | None, p: ProgressInfo, in_order: bool) -> bool:
        """Record progress for one playlist video. Returns False if it can't be matched."""
        if entry is None:
            return False
        if p.stage == STAGE_SAVED:
            self._set_entry(entry, ENTRY_DONE)
        elif entry.state != ENTRY_DONE:
            if p.stage in DOWNLOAD_STAGES:
                if entry.state != ENTRY_ACTIVE or entry.stage != p.stage:
                    entry.fraction = 0.0  # a new stream (e.g. audio after video) starts its own bar
                if p.fraction is not None:
                    entry.fraction = max(0.0, min(1.0, p.fraction))
                entry.speed, entry.eta = p.speed, p.eta
            else:  # merging / converting: the data is all here
                entry.fraction, entry.speed, entry.eta = 1.0, None, None
            entry.state = ENTRY_ACTIVE
            entry.running = True
            entry.stage = p.stage
        if in_order:
            # One-by-one fallback: yt-dlp goes through the playlist in order, so earlier
            # videos that never got saved were skipped (unavailable, private or failed).
            for e in item.entries:
                if e is entry:
                    break
                if e.state in (ENTRY_WAITING, ENTRY_ACTIVE):
                    self._set_entry(e, ENTRY_FAILED)
                    e.fraction = 0.0
            for e in item.entries:
                if e is not entry:
                    e.running = False
        return True

    @staticmethod
    def _entries_fraction(item: QueueItem) -> float:
        if not item.entries:
            return 0.0
        done = sum(1.0 if e.state in (ENTRY_DONE, ENTRY_FAILED) else e.fraction if e.state == ENTRY_ACTIVE else 0.0
                   for e in item.entries)
        return min(1.0, done / len(item.entries))

    # ------------------------------------------------- connection / stall watch

    def on_network(self, online: bool) -> None:
        self.online = online
        now = self.clock()
        for item in list(self.items):
            if not online and item.status == RUNNING:
                self._auto_pause(item, "network")
            elif (online and item.status == PAUSED and item.pause_reason in RESUME_DELAY
                  and now - item.paused_at >= RESUME_DELAY[item.pause_reason]):
                if item.auto_resumes >= MAX_AUTO_RESUMES:
                    item.pause_reason = "failing"  # stop retrying on our own; let the user decide
                    item.held_slots = 0
                    self.on_event("updated", item)
                else:
                    item.auto_resumes += 1
                    self.resume(item, auto=True)
                    self.on_event("auto_resumed", item)
        if online:
            self.schedule()

    def tick(self) -> None:
        """Call regularly: pauses downloads that have stalled."""
        now = self.clock()
        for item in self.items:
            if (item.status == RUNNING and item.pause_reason is None and item.downloading_stage
                    and now - item.last_good_progress > STALL_SECONDS):
                self._auto_pause(item, "slow")
