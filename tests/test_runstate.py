"""Lauf-Verzeichnis: Atomarität, Abbruch, Pfadprüfung."""

import json
import os
from pathlib import Path

import pytest

from begutachtung.runstate import (
    CANCELLED,
    DONE,
    FAILED,
    RUNNING,
    RunDir,
    RunState,
    find_run,
    list_runs,
)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "runs"


class TestAnlegen:
    def test_create_writes_state_and_config(self, root):
        run = RunDir.create("analyze", "/pfad/Akte.pdf", {"dpi": 400}, root=root)
        state = run.read_state()
        assert state is not None
        assert state.kind == "analyze"
        assert state.status == RUNNING
        assert state.source == "/pfad/Akte.pdf"
        assert run.read_config() == {"dpi": 400}

    def test_id_carries_timestamp_and_name(self, root):
        run = RunDir.create("analyze", "/pfad/Akte.pdf", root=root)
        assert "Akte" in run.id
        assert run.id.startswith("20")

    def test_awkward_filenames_do_not_break_the_id(self, root):
        run = RunDir.create("analyze", "/p/Akte Müller (2) & Co.pdf", root=root)
        assert "/" not in run.id and " " not in run.id
        assert run.path.is_dir()


class TestZustand:
    def test_write_is_atomic(self, root):
        """Die Oberflaeche liest im Sekundentakt waehrend geschrieben wird -
        eine halbe Datei darf sie nie zu sehen bekommen."""
        run = RunDir.create("analyze", "x.pdf", root=root)
        for i in range(1, 40):
            state = run.read_state()
            state.current = i
            run.write_state(state)
            # Nach jedem Schreiben muss die Datei fuer sich gueltiges JSON sein
            data = json.loads((run.path / "state.json").read_text(encoding="utf-8"))
            assert data["current"] == i
        assert not list(run.path.glob("*.tmp")), "Temporärdatei blieb liegen"

    def test_corrupt_state_reads_as_none_instead_of_raising(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        (run.path / "state.json").write_text("{ kaputt", encoding="utf-8")
        assert run.read_state() is None

    def test_unknown_fields_are_ignored(self, root):
        """Ein aelterer oder neuerer Lauf darf die Oberflaeche nicht sprengen."""
        run = RunDir.create("analyze", "x.pdf", root=root)
        data = json.loads((run.path / "state.json").read_text())
        data["ein_feld_aus_der_zukunft"] = 42
        (run.path / "state.json").write_text(json.dumps(data), encoding="utf-8")
        assert run.read_state().id == run.id

    def test_percent_and_elapsed(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        state = run.read_state()
        state.total, state.current = 200, 50
        assert state.percent == 25
        assert state.elapsed >= 0

    def test_percent_without_total_does_not_divide_by_zero(self):
        assert RunState(id="x").percent == 0

    def test_eta_needs_a_few_pages_first(self, root):
        """Eine Restzeit aus zwei Messpunkten waere eine Zahl, der man mehr
        glaubt als sie verdient."""
        state = RunState(id="x", total=100, current=2)
        assert state.eta_seconds is None
        state.current = 10
        assert state.eta_seconds is not None


class TestEreignisse:
    def test_append_and_tail(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        for i in range(60):
            run.append_event(f"Ereignis {i}", page=i)
        tail = run.tail_events(10)
        assert len(tail) == 10
        assert tail[-1]["msg"] == "Ereignis 59"
        assert tail[-1]["page"] == 59

    def test_half_written_last_line_is_skipped(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        run.append_event("gut")
        with open(run.path / "events.jsonl", "a", encoding="utf-8") as fh:
            fh.write('{"ts": 1, "msg": "abgeschni')
        assert [e["msg"] for e in run.tail_events()] == ["gut"]

    def test_tail_on_missing_file(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        assert run.tail_events() == []


class TestAbbruch:
    def test_cancel_flag(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        assert not run.cancel_requested
        run.request_cancel()
        assert run.cancel_requested

    def test_cancel_works_from_the_filesystem(self, root):
        """Das Terminal muss denselben Hebel haben wie die Oberflaeche."""
        run = RunDir.create("analyze", "x.pdf", root=root)
        (run.path / "CANCEL").touch()
        assert run.cancel_requested


class TestLebendigkeit:
    def test_running_without_worker_reads_as_failed(self, root):
        """Steht `running` in der Datei, ist der Prozess aber weg, hat ihn etwas
        abgeraeumt. Das als `running` anzuzeigen waere eine Luege, auf die der
        Nutzer wartet."""
        run = RunDir.create("analyze", "x.pdf", root=root)
        run.write_pid(2 ** 22)  # sicher nicht vergeben
        assert run.effective_status() == FAILED

    def test_own_pid_counts_as_alive(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        run.write_pid(os.getpid())
        assert run.worker_alive()
        assert run.effective_status() == RUNNING

    def test_terminal_status_is_not_second_guessed(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        state = run.read_state()
        state.status = DONE
        run.write_state(state)
        run.write_pid(2 ** 22)
        assert run.effective_status() == DONE

    def test_missing_pid_file(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        assert run.read_pid() is None
        assert not run.worker_alive()


class TestFinden:
    def test_find_by_id(self, root):
        run = RunDir.create("analyze", "x.pdf", root=root)
        assert find_run(run.id, root=root).path == run.path

    @pytest.mark.parametrize("evil", [
        "../../../etc", "..", "/etc/passwd", "a/b", "", "x/../../y", "..%2f..",
    ])
    def test_path_traversal_is_refused(self, root, evil):
        """Die Kennung kommt aus einer URL - sie an den Pfad zu haengen waere
        ein Weg aus dem Lauf-Verzeichnis heraus."""
        root.mkdir(parents=True, exist_ok=True)
        assert find_run(evil, root=root) is None

    def test_unknown_id(self, root):
        root.mkdir(parents=True, exist_ok=True)
        assert find_run("2026-01-01T00-00-00_gibtsnicht", root=root) is None

    def test_list_is_newest_first(self, root):
        ids = []
        for name in ("2026-01-01T00-00-00_a", "2026-06-01T00-00-00_b"):
            d = root / name
            d.mkdir(parents=True)
            RunDir(d).write_state(RunState(id=name))
            ids.append(name)
        assert [r.id for r in list_runs(root=root)] == list(reversed(ids))

    def test_list_on_missing_root(self, root):
        assert list_runs(root=root) == []
