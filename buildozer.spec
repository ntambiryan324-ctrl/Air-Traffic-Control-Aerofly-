[app]

# Application title
title = AeroflyATC

# Package name and domain
package.name = aeroflyatc
package.domain = com.ryan.aeroflyatc

# Source directory
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,env

# Application version
version = 1.0.0

# Required Python packages
requirements = python3,kivy,certifi,openssl

# Orientation
orientation = portrait

# Fullscreen mode
fullscreen = 0

# Android permissions
android.permissions = INTERNET,ACCESS_NETWORK_STATE

# Android SDK and NDK versions
android.api = 33
android.minapi = 21
android.ndk = 27b
android.accept_sdk_license = True

# Architecture
android.archs = arm64-v8a,armeabi-v7a

# Gradle options to avoid memory issues
android.gradle_options = org.gradle.jvmargs=-Xmx4096m

# Use legacy build tools
android.enable_androidx = True
android.presplash_model = both

# Features
android.features = android.hardware.screen.landscape,android.hardware.screen.portrait

[buildozer]

# Build logging level
log_level = 2

# Warn on root
warn_on_root = 1
