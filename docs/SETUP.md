# Set up another Fuzozo

## Compatibility comes first

The published address/signature profile is for **FZ1012, firmware 1.0.42**.
Only one physical unit was used to develop it. Another unit with the same name
may have a different firmware build or memory layout. Every hardware session
checks the enrolled MAC and reported version; RAM helpers additionally check
live function bytes and relevant state before writing.

A firmware mismatch is a stop condition. Never change the reported version or
remove signature checks merely to force it to run. No updater or downgrader is
provided. Other builds require a separately researched and tested profile.

## 1. Install and build

Follow the README installation commands. `build_helpers.py` compiles the
repository's assembly into `run/*.o` with clang. This step touches no robot and
requires no downloaded firmware. Test those helpers with the emulator suite
before experimenting with hardware.

## 2. Identify the device

Keep the robot awake. Attach a known data cable; charging alone proves nothing
about data access. List ports:

```sh
.venv/bin/python -m serial.tools.list_ports -v
```

The investigated adapter reports `VID:PID=1A86:7523` (CH340). macOS names such as
`/dev/cu.usbserial-210` can change after reconnecting. Do not select another
nearby serial device merely because its port looks similar.

Confirm which adapter disappears when you unplug this robot and returns when
reconnected. Stop other programs using it. Then perform the read-only probe:

```sh
.venv/bin/python setup_device.py --port /dev/cu.YOUR_PORT
```

This uses 460800 baud, 8N1, with RTS/DTR deasserted and sends only `macaddr get`
and `devget version`. It prints the MAC and firmware, not the raw boot log.
The model label in its output is the expected profile, **not independent model
detection**: verify FZ1012 on your physical device/box.

## 3. Enroll explicitly

With the physical identity confirmed, repeat the probe with its MAC:

```sh
.venv/bin/python setup_device.py --port /dev/cu.YOUR_PORT --mac YOUR_ROBOT_MAC
```

This rereads the device and checks your explicit MAC and supported firmware,
then creates private `run/device.json`. It refuses to overwrite an existing
enrollment. To switch robots, stop all bridge processes, back up/remove that
file yourself, and enroll the new robot. Do not reuse captures or RAM addresses
from a previous running session.

No cloud keys, Tuya login, official app activation, or government ID are needed
for this USB route. Bluetooth/cloud research tools and account secrets from the
original investigation are deliberately absent from this distribution.

## 4. Verify in stages

1. Set the AI endpoint/model in `config.json`; run `fuzozo_agent.py --doctor`.
2. Render a preview without hardware: `python speech_clip.py 'Hello, lab.' --output outputs/hello.wav`.
3. Start the panel and check connection; initial connection reads sound settings.
4. Enable sound, announce the test, and send a short phrase.
5. Confirm what was actually heard, not just the playback log.
6. Only then try the experimental microphone mode.

The volume slider affects factory sounds too. Generated speech adjusts the WAV
amplitude, but there is no independently verified custom-player gain control.
A permanent factory-sound suppression mode is not implemented.

## Stops, disconnects, and recovery

Use **Stop all** or Ctrl-C and allow cleanup to finish. Stop may wait for a
bounded transfer or network request; it is not an immediate power cutoff.
Closing the web tab does not stop the background server. To shut it down on
macOS, send SIGTERM to the `panel_server.py` PID listed in `run/panel-server.pid`
after confirming that PID still belongs to this server (`ps -p PID`).

If the adapter exists but identity fails, wake the robot and check connection.
If missing, check the cable and power. Do not repeatedly resend writes after a
missing acknowledgement. Sleep/reboot/fault markers invalidate sessions.

The panel can recover only an exactly identified interrupted microphone helper.
Unknown occupied scratch memory or changed signatures cause it to stop. A
normal device restart clears temporary RAM; reconnect and reverify afterward.
Do not factory-reset or flash a new firmware to recover this prototype.

If default port 8787 is occupied, the CLI can run `panel_server.py --port 8788`.
The desktop launcher always uses 8787. Use one bridge instance for the robot.
