@echo off
cd /d "%~dp0"
echo Pushing bot code to GitHub...
echo A browser window may open asking you to sign in to GitHub - sign in there.
echo.
git push -u origin main
echo.
echo Done. Check the lines above for errors.
pause
