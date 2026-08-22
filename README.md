# Havok PS4 behavior converter

This Python tool converts supported Fallout 4 PC behavior HKX packfiles to the
PS4 Havok layout. The PS4 layout also applies to PS5 when PS5 runs the PS4 game
through backward compatibility.

The converter changes object-member offsets, fixup offsets, section sizes, and
the packfile layout value. It does not change behavior states, events,
variables, expressions, or links.

## Scope

The tool supports these inputs:

- Fallout 4 behavior graph HKX files
- Havok `hk_2014.1.0-r1`
- Packfile version 11
- 64-bit, little-endian PC layout `08 01 00 01`
- Behavior classes that exist in the bundled or selected class XML database

The tool does not convert animation, character, project, or skeleton HKX files.
It does not support behavior imports or exports.

## Bundled class data

The package includes 908 class XML definitions from HkxPack-Plus commit
`8922f45a69f33b812215782670f84b095abfad0f`. The converter uses this data by
default. See [THIRD_PARTY.md](THIRD_PARTY.md) for its source and license.

Use `--class-db /path/to/classxml` only when you want to use a different class
database. The folder must use the HKXPack class XML format and contain files
named `<ClassName>_<version>.xml`.

## Convert one file

Run this command on Windows:

```text
py -3 hkx_behavior_to_ps4.py input\Behavior.hkx output\Behavior.hkx
```

Run this command on Linux or macOS:

```text
python3 hkx_behavior_to_ps4.py input/Behavior.hkx output/Behavior.hkx
```

Add `--force` to replace an existing output file.

## Convert a folder

```text
python3 hkx_behavior_to_ps4.py input_folder output_folder
```

Add `-r` to read subfolders.

The converter processes and validates all folder inputs before it changes a
destination file. If a commit fails, it restores prior destination files.

## Install the command

Python 3.10 or later is required.

```text
python3 -m pip install .
hkx-behavior-to-ps4 input.hkx output.hkx
```

The converter has no run-time dependencies outside the Python standard
library. It rejects DTDs and entity declarations in class XML.

## File safety

Each output first goes to a temporary file in the destination folder. The
converter validates the completed PS4 packfile before it replaces the
destination. A failed write does not truncate the prior output.

The output validator checks sections, fixups, object ranges, class references,
and class signatures. It does not make a converted game file legal to share.

## Tests

```text
python3 -B -m unittest discover -s test -p "test_*.py" -v
```

The tests build small synthetic class definitions and packfiles at run time.
The repository contains no copied game test data.

## License and project status

The source code and synthetic tests use the MIT license. The bundled class XML
data keeps its upstream license and attribution. See [LICENSE](LICENSE),
[NOTICE.md](NOTICE.md), and [THIRD_PARTY.md](THIRD_PARTY.md).

This independent project is not affiliated with Bethesda, Microsoft, Havok,
or Sony. Users must supply legally obtained input files.
