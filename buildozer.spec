[app]
title = AeroflyATC
package.name = aeroflyatc
package.domain = com.ryan.aeroflyatc
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas
source.exclude_dirs = .git,bin,build,__pycache__,.github
version = 1.5.0
requirements = python3,kivy
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,RECORD_AUDIO
android.api = 35
android.minapi = 23
android.ndk = 27b
android.accept_sdk_license = True
android.archs = arm64-v8a
android.gradle_options = org.gradle.jvmargs=-Xmx4096m
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 1
