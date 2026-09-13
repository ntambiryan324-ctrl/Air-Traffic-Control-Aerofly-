[app]
title = Aerofly Flight Companion
package.name = aeroflyatc
package.domain = org.aeroflycompanion
source.dir = .
source.include_exts = py,txt,png,jpg,jpeg,kv
version = 2.0.0
requirements = python3==3.11.16,hostpython3==3.11.16,kivy==2.3.0,pyjnius==1.6.1
orientation = portrait
fullscreen = 0
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
p4a.branch = master
p4a.commit = 4b4c5c2

[buildozer]
log_level = 2
warn_on_root = 0
