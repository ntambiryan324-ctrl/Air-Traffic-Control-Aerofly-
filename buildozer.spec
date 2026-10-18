[app]
title = Aerofly ATC
package.name = aeroflyatc
package.domain = org.aeroflycompanion
source.dir = .
source.include_exts = py,txt,png,jpg,jpeg,svg,kv
source.exclude_dirs = tests, tools
version = 4.0.0
icon.filename = %(source.dir)s/icon.png
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1
orientation = portrait
fullscreen = 0
android.api = 34
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.accept_sdk_license = True
android.private_storage = True
p4a.branch = master
p4a.local_recipes = p4a-recipes

[buildozer]
log_level = 2
warn_on_root = 0
