FREEWAY DRIFT — SOURCE CODE

RUN THE GAME
1. Extract this ZIP file to a folder on your computer.
2. Open index.html in your browser (Chrome, Firefox, Edge, or Safari).
3. Choose a car and select Take a drive.

No installation, account, internet connection, build step, or dependencies are required.
Keep index.html, style.css, game.js, and recorder.js together in the same folder.

RECORDING A DRIVE
1. Start driving, then click Record drive in the upper-right recorder panel.
2. In a browser with folder access (such as desktop Chrome or Edge), choose the
   project's recordings folder when prompted. The browser remembers this folder
   until the page is reloaded.
3. Stop recording, or let the two-minute limit stop it. The ZIP is saved in the
   selected folder as drive-<epoch_ms>.zip.

If folder access is unavailable, the ZIP downloads to the browser's normal
download location. Save again retries the same recording. Each ZIP contains
one session's images and JSONL metadata. Choose the recordings folder inside
the extracted project so the ZIP is kept with the project files.

CONTROLS
W / Up arrow: Accelerate
S / Down arrow: Brake, then reverse
A and D / Left and Right arrows: Steer
Space: Handbrake
R: Reset car to the starting road
Esc: Open menu / resume

OPTIONS
Civilian traffic: Toggle in the menu.
Auto accelerate: Toggle in the menu for steering-only cruising.
Engine sound: Click the music-note button.
Fullscreen: Click the fullscreen button, or use your browser's fullscreen command.

FILES
index.html — Interface and entry point
style.css — Interface appearance and responsive layout
game.js — City generation, drawing, vehicle physics, traffic, sound, and controls
recorder.js — Driving session capture and ZIP export

EDITING
Edit the files in any text editor, then reload index.html to see your changes.
Vehicle settings are in the cars array near the top of game.js.
The city uses Canvas 2D and an isometric projection, with simplified arcade driving physics.
This is an original driving sandbox inspired by the requested blocky-city style.
It contains no police, coins, scores, missions, or timers.
