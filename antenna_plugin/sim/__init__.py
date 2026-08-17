"""Simulation pipeline: config emits the runner YAML (self-contained, no
ems dependency), and simulate drives stackup -> gerbers -> config -> the
bundled monopole binary, then archives the dumps it wrote and installs the
viewer that draws them (antenna_plugin/viewer/). Nothing here renders HTML: the
pages are shipped files, and so are the help guides.

Driving a run of that binary is runsession (one invocation, watched for the
outputs it writes) over runcontrol (stop / sample / kill it -- the stop and
sample requests travel through the solver's --control file, the same on every
OS); hostos holds the little that still differs per OS (the binary's name,
launch flags), and runinfo reads back what a finished run's dump covers."""
