# Example: an agent session

What a typical agent loop looks like — real output from a POCO F5 over
wireless adb.

## 1. See what's attached

```console
$ droid-agent devices
diy9ljdyhiwgqglb    device        2312FPCA6G
```

## 2. Read the screen

```console
$ droid-agent dump
[ 1] >>    Search settings           ( 540, 497)  (header_view)
[ 2] |||   recyclerview              ( 540,1487)  (scroll_headers)
[ 3] ()    About phone               ( 540, 663)
[ 4] ()    System apps updater       ( 540, 817)
[ 5] ()    Security status           ( 540, 971)
[ 6] ()    Wi-Fi                     ( 540,1159)
[ 7] ()    Bluetooth                 ( 540,1313)
[ 8] ()    Mobile networks           ( 540,1467)
[ 9] ()    Interconnectivity         ( 540,1621)
[10] ()    Portable hotspot          ( 540,1775)
[11] ()    VPN                       ( 540,1929)
[12] ()    More connectivity options ( 540,2083)

12 elements · tap with `droid-agent tap <ref>`
```

## 3. Act

```console
$ droid-agent tap 3
tapped (540, 663)
```

## 4. Verify — the loop repeats

```console
$ droid-agent dump
[ 1] |v|   scrollview                ( 540,1332)  (scrollview)
[ 2] ()    3.0.307.0                 ( 540, 801)  (version_card_click_view)
[ 3] ()    Device name               ( 540,1407)  (device_name_card_view)
[ 4] ()    Storage                   ( 540,1548)  (device_memory_card_view)
[ 5] ()    OS version (for POCO)     ( 540,1750)
[ 6]  T    Android version           ( 242,1957)  (title)
[ 7]  T    16 BP2A.250605.031.A3     ( 790,1957)  (text_right)
```

The "About phone" screen opened — ref 3 did what its label said.

## JSON mode (what agents actually consume)

```console
$ droid-agent --json dump | jq '.[2]'
{
  "ref": 3,
  "kind": "button",
  "label": "About phone",
  "center": [540, 663],
  "bounds": [120, 590, 960, 736],
  "clickable": true,
  "editable": false,
  "scrollable": false,
  "enabled": true
}
```

## Recipe: scroll until found

```bash
for i in 1 2 3; do
  if droid-agent --json dump | grep -q '"label": "Apps"'; then
    break
  fi
  droid-agent swipe up
  droid-agent wait 0.5
done
```
