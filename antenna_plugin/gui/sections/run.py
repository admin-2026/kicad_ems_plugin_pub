"""The antenna flow's Run section: one solve, scored against the design target.

Everything about running -- the buttons, the two phases, the stop and the
snapshot, the worker thread, the archiving -- is the core's
``emkit.gui.sections.run.RunSection``. What is here is the three answers this
flow owes it:

  * the target a report is judged against is the application picked on the
    form (an antenna is designed *for* something: a band, an impedance, a
    return loss);
  * the run's single port is the feed marker the user placed on the board;
  * an archived report is scored against that target, so the report page can
    say how the antenna measured up.

The last two are not *written* here. A run can now be started from a command
line as well, and the two frontends must not answer them differently, so the
answers live headless in ``runjob.py`` and this section delegates -- adding
only what a window has and a shell does not: a log to say it in.
"""

from ... import runjob
from ...emkit.gui.sections.run import RunSection as CoreRunSection
from ...emkit.gui.sections.run import collect_run_params

__all__ = ["RunSection", "collect_run_params"]


class RunSection(CoreRunSection):
    def start_target(self):
        """The design target this run is being started for -- read on the main
        thread at Run, because the scoring happens on the worker and a form
        edited mid-run must not change what the run in flight was asked to
        achieve."""
        return self.page.form.current_application()

    def apply_ports(self, board, params):
        """The placed feed marker as the run's port (``runjob.apply_ports``),
        with what it found written to the run log."""
        runjob.apply_ports(board, params, note=lambda text: self.log(f"  {text}"))

    def score_report(self, dump_path):
        """Score the report just archived against the design target this run
        was started for, and leave the verdicts beside it so the report page
        can say how it measured up (runjob.score). A snapshot is scored like
        any other report: it overwrites the previous verdicts as it overwrites
        the numbers they are about.

        Never fatal -- a run nobody can score still has a report to read."""
        try:
            payload = runjob.score(dump_path, self._target)
        except (OSError, RuntimeError) as exc:
            self.log(f"  could not score the report: {exc}")
            return
        if payload:
            self.log(f"  against {payload['target']}: {payload['overall']}")
