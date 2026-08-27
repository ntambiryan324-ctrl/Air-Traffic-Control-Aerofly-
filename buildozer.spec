[app]
title = AeroflyATC
package.name = aeroflyatc
package.domain = com.ryan.aeroflyatc
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,env
version = 1.0.0
requirements = python3,kivy,certifi,openssl

orientation = portrait
osx.python_version = 3
osx.kivy_version = 2.3.0

fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE

android.api = 33
android.minapi = 21
android.ndk = 25.2.9519653
android.accept_sdk_license = True

android.archs = arm64-v8a, armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1

