# Havok PS4 behavior converter

This Python tool converts supported Fallout 4 PC behavior HKX files to the PS4
Havok layout. This layout also works when a PS5 runs the PS4 game.

The tool supports:

- Havok `hk_2014.1.0-r1`
- Packfile version 11
- 64-bit, little-endian PC layout `08 01 00 01`
- Classes in the included class XML database

The tool does not convert animation, character, project, or skeleton HKX files.

## Requirements

Install Python 3.10 or later. The tool has no external run-time dependencies.

## Use

Convert one file on Windows:

```text
py -3 hkx_behavior_to_ps4.py input\Behavior.hkx output\Behavior.hkx
```

Convert one file on Linux or macOS:

```text
python3 hkx_behavior_to_ps4.py input/Behavior.hkx output/Behavior.hkx
```

Convert all supported files in a folder:

```text
python3 hkx_behavior_to_ps4.py input_folder output_folder
```

Use `-r` to include subfolders. Use `--force` to replace existing output files.

You can also install the command:

```text
python3 -m pip install .
hkx-behavior-to-ps4 input.hkx output.hkx
```

## Tests

```text
python3 -B -m unittest discover -s test -p "test_*.py" -v
```

## License

The source code uses the [MIT license](LICENSE).

This project is not affiliated with Bethesda, Microsoft, Havok, or Sony. You
must supply legally obtained input files.
