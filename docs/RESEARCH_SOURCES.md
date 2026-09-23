# Where are the C files?

The original lab workspace contained **393 C/C++ source and header files**
(excluding Python environments). All were under `research/`: third-party SDK,
driver and example material consulted during the investigation. None is an
input to this repository's build script. The count includes overlapping
reference material and does not represent 393 independently required files.

The executable bridge is Python. Its device-side helpers are the published
`ram_*.S` ARM assembly files, compiled directly by `build_helpers.py`. There is
no missing C compilation step and no unpublished C helper required to build
those objects. The public repository is not the full source of Fuzozo's factory
firmware.

## References worth reading

| Upstream source | What to look for |
| --- | --- |
| [Beken IDK: shell_task.c](https://github.com/bekencorp/bk_idk/blob/650e754e12fe1e43c37ce2316a973668b033fd48/components/bk_cli/shell_task.c) | Text-mode console input and character handling |
| [Beken IDK: cli_vfs.c](https://github.com/bekencorp/bk_idk/blob/650e754e12fe1e43c37ce2316a973668b033fd48/components/bk_cli/cli_vfs.c) | Filesystem command arguments and writes |
| [Beken IDK: cli_psram.c](https://github.com/bekencorp/bk_idk/blob/650e754e12fe1e43c37ce2316a973668b033fd48/components/bk_cli/cli_psram.c) | PSRAM allocation/debug commands |
| [Beken IDK: uart_debug/udebug.c](https://github.com/bekencorp/bk_idk/blob/650e754e12fe1e43c37ce2316a973668b033fd48/components/bk_cli/uart_debug/udebug.c) | Binary UART debugging alongside the console |
| [Beken AVDK AI](https://github.com/bekencorp/bk_avdk_ai) — `components/multimedia/aud/aud_tras_drv.c` | Audio transfer and callback behavior |
| [Beken AI development kit](https://github.com/bekencorp/bk_aidk/tree/b72e1cb86831d8957fe40abb819aca526e7a01d2) | Audio-engine/application examples |
| [Tuya agentic-kit](https://github.com/tuya/agentic-kit/tree/ff8e85c1edbe47f152765e48fa9cbf1aba13e337) | BLE provisioning and agent/audio examples |
| [Tuya BLE smart-kettle example](https://github.com/tuya/tuya-iotos-embeded-demo-ble-smart-kettle/tree/fad53fb05e19293a30947216c59f4fc258440459) | Reference Tuya BLE application structure, not Fuzozo-specific code |
| [BLE SDK reference mirror](https://github.com/hjytry/tuya-ble-sdk/tree/815c07120e96372e8746e9d01a21381a8fdd8655) | SDK packet/storage/transport implementation; this is a third-party mirror |

Branch links may move. [reference-sources.json](reference-sources.json) records
exact Git blob IDs and API URLs for individual downloaded Beken files whose
contents were matched byte-for-byte to their upstream Git trees. The pinned
repository links above use the commits present in the original local clones.

A Git blob API URL returns JSON containing the source as base64 `content`.
Its `sha` identifies the precise source bytes. The index's `git_tree_sha` is a
tree object, not a commit ID. Preserve upstream notices and consult each
project's own license when reusing its code; this repository's MIT license does
not relicense the references. The reference files are linked, not bundled.

These SDKs explain likely mechanisms. They are **not proof that the installed
robot uses the same function addresses, build options or complete source**.
That is why the bridge additionally checks live firmware signatures and state.

## What someone can reproduce with this repository

- Build the included RAM helpers from source and run their emulator tests.
- Inspect/enroll a physically identified robot with the supported firmware.
- Attempt the published USB microphone, speech and sound-control paths.
- Read and extend the implementation, including its runtime guards and failure
  handling, and connect a different AI/speech service.

Only one physical FZ1012 was used for the original work. Another unit must pass
identity, version, code-signature and memory-state checks; its success is not
established merely by having the same model name.

## What is not a complete reproducible package yet

The repository does not include the original app/firmware binaries, private
captures, account credentials or raw device keys. It also does not include all
of the lab's app-metadata/disassembly utilities or Bluetooth/cloud investigation
clients. The reverse-engineering guide describes that work, but the published
code implements the resulting USB bridge, not every historical discovery step.

Therefore it is a usable starting point for continuing research on the
supported profile, not a universal method for automatically reverse-engineering
any Fuzozo or porting to arbitrary firmware. A different build needs renewed
analysis and a separately verified profile. Linking the C references helps
readers follow the reasoning without presenting vendor SDK code as recovered
Fuzozo source.
