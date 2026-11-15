import threading

import pytest

from models.media import DownloadResult, MediaInfo, PlaylistEntry, ProgressInfo, QualityOption
from services import download_queue as dq

Q720 = QualityOption("720p", 720)


class FakeJob:
    def __init__(self, spec=None):
        self.spec = spec
        self.pause_event = threading.Event()
        self.cancel_event = threading.Event()
        self.completed_files = set()


def T(item, n=0):
    """Id of the item's n-th task (results and progress are reported per task)."""
    return item.tasks[n].id


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def env():
    clock = Clock()
    spawned, events = [], []
    queue = dq.DownloadQueue(
        job_factory=lambda task_id, spec, option: FakeJob(spec),
        spawn=spawned.append,
        on_event=lambda kind, item: events.append((kind, item.id)),
        max_concurrent=2,
        clock=clock,
    )
    return queue, spawned, events, clock


def media(n: int, playlist: bool = False) -> MediaInfo:
    entries = [PlaylistEntry(i, f"v{i}") for i in range(1, 6)] if playlist else []
    return MediaInfo(url=f"https://youtu.be/{n}", title=f"Video {n}", is_playlist=playlist, entries=entries)


def statuses(queue):
    return [i.status for i in queue.items]


def test_runs_at_most_n_at_once_in_order(env):
    queue, spawned, _, _ = env
    for n in range(4):
        queue.add(media(n), Q720, None)
    assert statuses(queue) == ["running", "running", "queued", "queued"]
    assert [t.item.id for t in spawned] == [1, 2]

    queue.on_result(T(queue.items[0]), DownloadResult(1, 1))
    assert statuses(queue) == ["completed", "running", "running", "queued"]
    assert spawned[-1].item.id == 3


def test_raising_the_limit_starts_waiting_items(env):
    queue, spawned, _, _ = env
    for n in range(4):
        queue.add(media(n), Q720, None)
    queue.set_max_concurrent(3)
    assert statuses(queue).count("running") == 3
    queue.set_max_concurrent(1)  # lowering never interrupts running downloads
    assert statuses(queue).count("running") == 3


def test_user_pause_and_resume(env):
    queue, spawned, _, _ = env
    a = queue.add(media(1), Q720, None)
    queue.add(media(2), Q720, None)
    c = queue.add(media(3), Q720, None)

    queue.pause(a)
    assert a.status == "pausing" and a.job.pause_event.is_set()
    queue.on_result(T(a), DownloadResult(0, 1, paused=True))
    assert a.status == "paused" and a.pause_reason == "user"
    assert c.status == "running"  # the freed slot went to the next item

    queue.resume(a)
    assert a.status == "queued"  # waits for a free slot
    queue.on_result(T(c), DownloadResult(1, 1))
    assert a.status == "running" and spawned[-1].item is a and not a.job.pause_event.is_set()


def test_pausing_a_waiting_item_skips_it(env):
    queue, _, _, _ = env
    queue.set_max_concurrent(1)
    queue.add(media(1), Q720, None)
    b = queue.add(media(2), Q720, None)
    c = queue.add(media(3), Q720, None)
    queue.pause(b)
    assert b.status == "paused"
    queue.on_result(T(queue.items[0]), DownloadResult(1, 1))
    assert b.status == "paused" and c.status == "running"


def test_cancel_running_and_waiting(env):
    queue, _, events, _ = env
    queue.set_max_concurrent(1)
    a = queue.add(media(1), Q720, None)
    b = queue.add(media(2), Q720, None)
    queue.cancel(b)
    assert b.status == "cancelled" and ("cancelled", b.id) in events
    queue.cancel(a)
    assert a.job.cancel_event.is_set() and a.status == "running"
    queue.on_result(T(a), DownloadResult(0, 1, cancelled=True))
    assert a.status == "cancelled"


def test_network_loss_pauses_everything_and_resumes(env):
    queue, spawned, events, clock = env
    a = queue.add(media(1), Q720, None)
    b = queue.add(media(2), Q720, None)
    c = queue.add(media(3), Q720, None)

    queue.on_network(False)
    assert a.status == b.status == "pausing" and a.pause_reason == "network"
    assert ("auto_paused", a.id) in events
    for item in (a, b):
        queue.on_result(T(item), DownloadResult(0, 1, paused=True, network_error=True))
    assert c.status == "queued"  # nothing new starts while offline

    queue.on_network(True)
    assert a.status == "paused"  # waits RESUME_DELAY before retrying
    clock.now += dq.RESUME_DELAY["network"]
    queue.on_network(True)
    assert a.status == "running" and b.status == "running" and c.status == "queued"
    assert ("auto_resumed", a.id) in events


def test_ytdlp_network_error_counts_as_auto_pause(env):
    queue, _, events, clock = env
    a = queue.add(media(1), Q720, None)
    queue.on_result(T(a), DownloadResult(0, 1, paused=True, network_error=True))
    assert a.status == "paused" and a.pause_reason == "network" and ("auto_paused", a.id) in events
    clock.now += 5
    queue.on_network(True)
    assert a.status == "running"


def test_user_pause_is_not_auto_resumed(env):
    queue, _, _, clock = env
    a = queue.add(media(1), Q720, None)
    queue.pause(a)
    queue.on_result(T(a), DownloadResult(0, 1, paused=True))
    clock.now += 100
    queue.on_network(True)
    assert a.status == "paused"


def test_stalled_download_pauses_and_resumes(env):
    queue, _, _, clock = env
    a = queue.add(media(1), Q720, None)
    queue.on_progress(T(a), ProgressInfo("download_video", 0.1, speed=2_000_000))
    clock.now += dq.STALL_SECONDS - 1
    queue.on_progress(T(a), ProgressInfo("download_video", 0.1, speed=500))  # crawling
    queue.tick()
    assert a.status == "running"
    clock.now += 2
    queue.tick()
    assert a.status == "pausing" and a.pause_reason == "slow"
    queue.on_result(T(a), DownloadResult(0, 1, paused=True))
    clock.now += dq.RESUME_DELAY["slow"]
    queue.on_network(True)
    assert a.status == "running"


def test_gives_up_after_repeated_failures(env):
    queue, _, _, clock = env
    a = queue.add(media(1), Q720, None)
    for _ in range(dq.MAX_AUTO_RESUMES):
        queue.on_result(T(a), DownloadResult(0, 1, paused=True, network_error=True))
        clock.now += 5
        queue.on_network(True)
        assert a.status == "running"
    queue.on_result(T(a), DownloadResult(0, 1, paused=True, network_error=True))
    clock.now += 5
    queue.on_network(True)
    assert a.status == "paused" and a.pause_reason == "failing"
    queue.resume(a)  # the user can still retry
    assert a.status == "running" and a.auto_resumes == 0


def test_progress_and_playlist_fraction(env):
    queue, _, events, _ = env
    a = queue.add(media(1, playlist=True), Q720, [1, 2, 3, 4])
    assert a.total == 4
    queue.on_progress(T(a), ProgressInfo("download_video", 0.5, item_number=2, item_count=4))
    assert a.fraction == pytest.approx((1 + 0.5) / 4)
    queue.on_progress(T(a), ProgressInfo("saved", 1.0, item_number=2, item_count=4))
    assert a.fraction == pytest.approx(2 / 4) and ("saved", a.id) in events


def test_failed_item_frees_its_slot(env):
    queue, _, _, _ = env
    queue.set_max_concurrent(1)
    a = queue.add(media(1), Q720, None)
    b = queue.add(media(2), Q720, None)
    queue.on_error(T(a), "Video unavailable")
    assert a.status == "failed" and a.error == "Video unavailable" and b.status == "running"


def test_duplicates_and_clear_finished(env):
    queue, _, events, _ = env
    a = queue.add(media(1), Q720, None)
    assert queue.find_duplicate(media(1), Q720, None) is a
    assert queue.find_duplicate(media(1), QualityOption("1080p", 1080), None) is None
    queue.on_result(T(a), DownloadResult(1, 1))
    assert queue.find_duplicate(media(1), Q720, None) is None  # finished items don't count
    queue.add(media(2), Q720, None)
    queue.clear_finished()
    assert [i.id for i in queue.items] == [2] and ("removed", a.id) in events
    assert queue.has_active()


def test_offline_add_waits(env):
    queue, spawned, _, _ = env
    queue.on_network(False)
    a = queue.add(media(1), Q720, None)
    assert a.status == "queued" and not spawned
    queue.on_network(True)
    assert a.status == "running"


def P(stage, index, fraction=None, speed=None):
    return ProgressInfo(stage, fraction, speed, None, playlist_index=index)


def test_playlist_tracks_each_video(env):
    queue, _, events, _ = env
    item = queue.add(media(1, playlist=True), Q720, [2, 3, 5])
    assert [(e.index, e.title, e.state) for e in item.entries] == [
        (2, "v2", "waiting"), (3, "v3", "waiting"), (5, "v5", "waiting")]

    queue.on_progress(T(item), P("download_video", 2, 0.5, 100_000))
    e2, e3, e5 = item.entries
    assert e2.state == "active" and e2.fraction == 0.5 and e2.speed == 100_000
    assert item.fraction == pytest.approx(0.5 / 3)

    queue.on_progress(T(item), P("merging", 2))
    assert e2.fraction == 1.0 and e2.stage == "merging"
    queue.on_progress(T(item), P("saved", 2, 1.0))
    assert e2.state == "done" and item.fraction == pytest.approx(1 / 3)

    # Video 3 is skipped by yt-dlp (unavailable): the next update is for video 5.
    queue.on_progress(T(item), P("download_video", 5, 0.25))
    assert e3.state == "failed" and e5.state == "active"
    assert item.entry_counts() == {"waiting": 0, "active": 1, "done": 1, "failed": 1}
    assert ("progress", item.id) in events


def test_playlist_entries_survive_pause_and_finish(env):
    queue, _, _, _ = env
    item = queue.add(media(1, playlist=True), Q720, None)
    e1, e2 = item.entries[:2]
    queue.on_progress(T(item), P("saved", 1, 1.0))
    queue.on_progress(T(item), P("download_video", 2, 0.4))
    queue.pause(item)
    queue.on_progress(T(item), P("download_video", 2, 0.45))  # late update while pausing
    queue.on_result(T(item), DownloadResult(1, 5, paused=True))
    assert item.status == "paused" and e1.state == "done" and e2.state == "active"

    queue.resume(item)
    queue.on_progress(T(item), P("processing", 1, 1.0))  # yt-dlp re-checks finished videos
    assert e1.state == "done" and e2.state == "active"
    for i in (2, 3, 4):
        queue.on_progress(T(item), P("saved", i, 1.0))
    queue.on_result(T(item), DownloadResult(4, 5))
    assert [e.state for e in item.entries] == ["done", "done", "done", "done", "failed"]
    assert item.status == "completed"


def playlist(n: int, count: int = 5) -> MediaInfo:
    """A playlist whose videos have their own links, so they download in parallel."""
    entries = [PlaylistEntry(i, f"v{i}", url=f"https://youtu.be/p{n}v{i}") for i in range(1, count + 1)]
    return MediaInfo(url=f"https://youtube.com/playlist?list={n}", title=f"List {n}", is_playlist=True, entries=entries)


def task_of(item, index):
    return next(t for t in item.tasks if t.entry.index == index)


def running_indexes(item):
    return [t.entry.index for t in item.running_tasks]


def test_playlist_videos_download_in_parallel(env):
    queue, spawned, _, _ = env
    queue.set_max_concurrent(3)
    pl = queue.add(playlist(1), Q720, [1, 2, 4, 5])
    assert pl.per_video and len(pl.tasks) == 4 and pl.status == "running"
    assert running_indexes(pl) == [1, 2, 4]
    spec = spawned[0].job.spec
    assert (spec.url, spec.playlist, spec.folder, spec.index) == ("https://youtu.be/p1v1", False, "List 1", 1)
    assert [e.running for e in pl.entries] == [True, True, True, False]

    queue.on_progress(T(pl, 1), ProgressInfo("download_video", 0.5, 1_000_000))
    queue.on_progress(T(pl, 0), ProgressInfo("saved", 1.0))
    assert pl.entries[0].state == "done" and pl.entries[1].fraction == 0.5
    assert pl.fraction == pytest.approx(1.5 / 4)
    assert pl.entry_counts() == {"waiting": 1, "active": 2, "done": 1, "failed": 0}

    queue.on_result(T(pl, 0), DownloadResult(1, 1))
    assert running_indexes(pl) == [2, 4, 5]  # the freed slot went to the next video
    queue.on_error(T(pl, 1), "Private video")  # one video fails; the rest carry on
    assert pl.entries[1].state == "failed" and pl.status == "running"
    for i in (4, 5):
        queue.on_result(T(pl, [1, 2, 4, 5].index(i)), DownloadResult(1, 1))
    assert pl.status == "completed" and pl.result == DownloadResult(3, 4)
    assert [e.state for e in pl.entries] == ["done", "failed", "done", "done"]


def test_limit_is_shared_by_playlists_and_videos(env):
    queue, _, _, _ = env  # limit 2
    pl = queue.add(playlist(1, count=3), Q720, None)
    single = queue.add(media(9), Q720, None)
    assert running_indexes(pl) == [1, 2] and single.status == "queued"  # older item first
    queue.on_result(T(pl, 0), DownloadResult(1, 1))
    assert running_indexes(pl) == [2, 3] and single.status == "queued"
    queue.on_result(T(pl, 1), DownloadResult(1, 1))
    assert single.status == "running"


def test_playlist_pause_resume_and_network(env):
    queue, spawned, events, clock = env
    queue.set_max_concurrent(3)
    pl = queue.add(playlist(1), Q720, None)
    other = queue.add(media(9), Q720, None)
    queue.on_progress(T(pl, 0), ProgressInfo("download_video", 0.3, 1_000_000))

    queue.pause(pl)
    assert pl.status == "pausing" and all(t.job.pause_event.is_set() for t in pl.running_tasks)
    for n in (0, 1):
        queue.on_result(T(pl, n), DownloadResult(0, 1, paused=True))
    assert pl.status == "pausing"  # still waiting for the third video to stop
    queue.on_result(T(pl, 2), DownloadResult(0, 1, paused=True))
    assert pl.status == "paused" and other.status == "running"
    assert pl.entries[0].state == "active" and not pl.entries[0].running  # keeps its 30 %

    queue.resume(pl)
    assert running_indexes(pl) == [1, 2]  # 2 free slots (the single video holds one)

    # One video hits a network error: the whole playlist pauses and keeps its slots.
    queue.on_result(T(pl, 0), DownloadResult(0, 1, paused=True, network_error=True))
    assert pl.status == "pausing" and pl.pause_reason == "network" and ("auto_paused", pl.id) in events
    queue.on_result(T(pl, 1), DownloadResult(0, 1, paused=True, network_error=True))
    assert pl.status == "paused" and pl.held_slots == 2
    queue.on_result(T(other), DownloadResult(1, 1))
    assert queue.running_count() == 2
    clock.now += dq.RESUME_DELAY["network"]
    queue.on_network(True)
    assert running_indexes(pl) == [1, 2, 3]


def test_playlist_cancel_stops_every_video(env):
    queue, _, events, _ = env
    pl = queue.add(playlist(1), Q720, None)
    queue.cancel(pl)
    assert all(t.job.cancel_event.is_set() for t in pl.tasks) and pl.status == "running"
    queue.on_result(T(pl, 0), DownloadResult(0, 1, cancelled=True))
    assert pl.status == "running"
    queue.on_result(T(pl, 1), DownloadResult(0, 1, cancelled=True))
    assert pl.status == "cancelled" and ("cancelled", pl.id) in events
    assert not any(e.running for e in pl.entries)


def test_playlist_where_every_video_fails(env):
    queue, _, _, _ = env
    pl = queue.add(playlist(1, count=2), Q720, None)
    queue.on_error(T(pl, 0), "Sign in to confirm your age")
    queue.on_error(T(pl, 1), "Sign in to confirm your age")
    assert pl.status == "failed" and pl.error == "Sign in to confirm your age"


def test_playlist_without_video_links_falls_back_to_one_by_one(env):
    queue, _, _, _ = env
    pl = queue.add(media(1, playlist=True), Q720, [1, 2])  # entries have no url
    assert not pl.per_video and len(pl.tasks) == 1
    spec = pl.job.spec
    assert spec.playlist and spec.items == [1, 2] and spec.total == 2


def test_lowering_the_limit_lets_running_videos_finish(env):
    queue, _, _, _ = env
    queue.set_max_concurrent(3)
    pl = queue.add(playlist(1), Q720, None)
    queue.set_max_concurrent(1)
    assert len(pl.running_tasks) == 3  # nothing is interrupted
    for n in (0, 1):
        queue.on_result(T(pl, n), DownloadResult(1, 1))
    assert running_indexes(pl) == [3]
    queue.on_result(T(pl, 2), DownloadResult(1, 1))
    assert running_indexes(pl) == [4] and pl.status == "running"
