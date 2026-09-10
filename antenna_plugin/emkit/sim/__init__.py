"""The simulation pipeline: stackup -> gerbers -> the runner YAML -> the
bundled solver binary, then the dumps it wrote and the viewer that draws them.

``simulate`` drives it and holds the board facts (the stackup it reads, the
gerbers it plots, where a run's files go, where the binary is). What the YAML
*says* is not here: each flow writes its own schema, so ``simulate.write_config``
hands off to the plugin's own ``config`` module. Nothing here renders HTML --
the viewer pages are shipped files, and so are the help guides.

Driving a run of the binary is runsession (one invocation, watched for the
outputs it writes) over runcontrol (stop / sample / kill it -- the stop and
sample requests travel through the solver's --control file, the same on every
OS); hostos holds the little that still differs per OS (the binary's name,
launch flags), and runinfo reads back what a finished run's dump covers.
"""
