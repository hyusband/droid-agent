# droid-agent demo — real session against a POCO F5
# Render: vhs scripts/demo.tape   (needs vhs + ffmpeg on PATH)

Output assets/demo.gif

Set Shell "powershell"
Set FontSize 14
Set FontFamily "Cascadia Code"
Set Width 1280
Set Height 720
Set TypingSpeed 55ms
Set PlaybackSpeed 1.0

# Dark theme + magenta accent (matches README)
Set Theme {
	"name": "droid-agent",
	"black": "#1c1024",
	"red": "#ff5f87",
	"green": "#4ae29c",
	"yellow": "#e3c341",
	"blue": "#6c8cff",
	"purple": "#c800df",
	"cyan": "#54e6e6",
	"white": "#e8e6f0",
	"brightBlack": "#6b5f78",
	"brightRed": "#ff87a6",
	"brightGreen": "#7bf0bd",
	"brightYellow": "#f0dc7a",
	"brightBlue": "#96adff",
	"brightPurple": "#e05cff",
	"brightCyan": "#8ff0f0",
	"brightWhite": "#ffffff",
	"background": "#130b19",
	"foreground": "#e8e6f0",
	"cursorColor": "#c800df",
	"selectionBackground": "#3d2650"
}

# --- the story: devices → dump → tap → verify → back ---
Type "droid-agent devices"
Enter
Sleep 2.5s

Type "droid-agent open com.android.settings"
Enter
Sleep 2.5s

Type "droid-agent dump"
Enter
Sleep 3.5s

Type "droid-agent tap 3"
Enter
Sleep 3s

Type "droid-agent dump"
Enter
Sleep 4s

Type "droid-agent key back"
Enter
Sleep 3s
