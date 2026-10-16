# Original Audio for Kodi

A small Kodi service add-on that switches every movie and episode to its **original-language audio track** when playback starts.

Kodi's own "Preferred audio language: Original stream" only works when the file marks a track as original, and most releases and streams don't. This add-on looks up the title's original language instead, and picks the matching track.

## How it works

1. When a video starts, the add-on reads the IMDb / TMDb / TVDB ids that your player add-on attached to the item.
2. It looks up the original language:
   - **TMDb**, if you entered your own TMDb API key in the settings, then
   - **Wikidata** (no key needed) as the fallback. For episodes it uses the language of the series.
3. It selects the audio track in that language. When there are several, it skips commentary and audio-description tracks and prefers the one with the most channels.
4. If the language can't be found, or the file has no track in it, nothing is changed (a track flagged as "original" is used if there is one).

Results are cached per title, so other episodes of the same show don't need another lookup.

## Install

1. Download `service.originalaudio-x.y.z.zip` from [Releases](../../releases).
2. In Kodi: **Settings → Add-ons → Install from zip file** and pick the zip.

## Settings

| Setting | Default | |
|---|---|---|
| Switch to original audio | On | Turn the add-on on or off |
| Show a notification when switching | On | Shows e.g. `Korean` for a few seconds |
| TMDb API key (optional) | empty | Your TMDb **API Key** (the short v3 key, not the long "Read Access Token"). With a key TMDb is asked first; Wikidata is always the fallback |

## Notes

- It only acts once, when playback starts, so you can still change the audio track yourself.
- The ids come from the add-on that plays the video. Library items and most video add-ons provide them. When an item has none (some anime add-ons, `.strm` files), the add-on looks the show or movie up by its title instead (TMDb search with a key, else Wikidata, counting only titles that have an IMDb entry), and looks again a few times during the first minute in case another add-on adds the ids later.
- Troubleshooting: lines starting with `[originalaudio]` in `kodi.log` show the ids, the language found and the track chosen.

## Credits

Written with help from Claude (Anthropic).

## License

MIT
