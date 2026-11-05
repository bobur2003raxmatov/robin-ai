@echo off
REM ROBIN Android ilovasini yig'ish va serverga joylash (Dashboard -> Download App)
cd /d "%~dp0"
call flutter build apk --release || exit /b 1
if not exist "..\..\database\apps" mkdir "..\..\database\apps"
copy /Y "build\app\outputs\flutter-apk\app-release.apk" "..\..\database\apps\ROBIN.apk"
echo Tayyor: database\apps\ROBIN.apk
