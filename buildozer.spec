[app]
title = Aerofly Flight Companion
package.name = aeroflyatc
package.domain = org.aeroflycompanion
source.dir = .
source.include_exts = py,txt,png,jpg,jpeg,svg,kv
version = 2.0.0
requirements = python3,kivy==2.3.0,requests,openssl,plyer
garden_requirements = mapview
orientation = portrait
fullscreen = 0
android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.permissions = INTERNET,ACCESS_NETWORK_STATE,RECORD_AUDIO,POST_NOTIFICATIONS
android.accept_sdk_license = True
p4a.branch = v2024.01.21
p4a.commit = HEAD

[buildozer]
log_level = 2
warn_on_root = 0
