Zip any addon folder that contains an `addon.json` manifest and the Python entry file it references.

Example:

`sample_addons/hello_status_addon/`

Ready-made addon sources in this repo:
- `sample_addons/administrative_tools_addon/`
- `sample_addons/equipment_manager_addon/`
- `sample_addons/hello_status_addon/`

Required manifest fields:
- `id`
- `name`
- `version`
- `entry_point` in the format `file.py:function_name`

Navigation can be declared in either of these ways:
- Simple addon: `workspace` + `nav_label`
- Multi-entry addon: `nav_entries`, where each item has `entry_id`, `nav_label`, and `workspace`

The entry function receives a context object with:
- `database`
- `deployment_service`
- `addon_dir`

The function must return a `QWidget`.
