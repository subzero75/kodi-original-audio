import json, os, time
from urllib.parse import quote
from urllib.request import Request, urlopen
import xbmc, xbmcaddon, xbmcgui, xbmcvfs
from resources.lib import hold

ADDON_ID = 'service.originalaudio'
UA = 'Kodi-OriginalAudio/1.0 (https://github.com/subzero75/kodi-original-audio)'
CACHE = os.path.join(xbmcvfs.translatePath('special://profile/addon_data/%s/' % ADDON_ID), 'cache.json')
CACHE_DAYS = 60


def addon():
    return xbmcaddon.Addon(ADDON_ID)


def setting_on(key):
    try:
        return addon().getSettingBool(key)
    except Exception:
        return False


def log(msg, level=xbmc.LOGINFO):
    xbmc.log('[originalaudio] %s' % msg, level)


def rpc(method, params=None):
    q = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}
    return json.loads(xbmc.executeJSONRPC(json.dumps(q))).get('result') or {}


def get_json(url, timeout=8):
    with urlopen(Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'}), timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def lang_name(code):
    """'ko', 'kor', 'ger', 'deu', 'German' -> 'German' (so 2/3-letter and B/T codes compare equal)."""
    code = (code or '').strip()
    if not code or code.lower() in ('und', 'unk', 'mis', 'mul', 'zxx', 'n/a'):
        return ''
    return xbmc.convertLanguage(code, xbmc.ENGLISH_NAME) or code


# ---------------------------------------------------------------- ids of what is playing

def _valid(kind, value):
    """An id as it should look; Kodi hands back the label text itself (e.g.
    'VideoPlayer.Property(tmdb_id)') for a property nobody set."""
    value = str(value or '').strip()
    if kind == 'imdb':
        return value if value.startswith('tt') and value[2:].isdigit() else ''
    return value if value.isdigit() else ''


def playing_ids(player):
    ids, kind = {}, 'movie'
    try:
        tag = player.getVideoInfoTag()
        kind = tag.getMediaType() or kind
        for k in ('imdb', 'tmdb', 'tvdb'):
            v = _valid(k, tag.getUniqueID(k))
            if v:
                ids[k] = v
        if not ids.get('imdb') and (tag.getIMDBNumber() or '').startswith('tt'):
            ids['imdb'] = tag.getIMDBNumber()
        if tag.getTVShowTitle():
            kind = 'episode'
    except Exception as e:
        log('no info tag: %s' % e)
    if xbmc.getInfoLabel('VideoPlayer.TVShowTitle'):
        kind = 'episode'
    if not ids.get('imdb'):
        v = _valid('imdb', xbmc.getInfoLabel('VideoPlayer.IMDBNumber'))
        if v:
            ids['imdb'] = v
    # Some add-ons only set these as properties
    for k, props in (('imdb', ('imdb_id', 'imdbnumber', 'tvshow.imdb_id')),
                     ('tmdb', ('tmdb_id', 'tvshow.tmdb_id')),
                     ('tvdb', ('tvdb_id', 'tvshow.tvdb_id'))):
        if not ids.get(k):
            for p in props:
                v = _valid(k, xbmc.getInfoLabel('VideoPlayer.Property(%s)' % p)) or \
                    _valid(k, xbmc.getInfoLabel('ListItem.Property(%s)' % p))
                if v:
                    ids[k] = v
                    break
    return ids, kind


def playing_title(kind):
    """(title, year) of the show or movie, for a lookup by name when no add-on gave ids
    (e.g. anime add-ons, .strm files). The show's title for an episode."""
    title = xbmc.getInfoLabel('VideoPlayer.TVShowTitle') if kind == 'episode' else ''
    title = title or xbmc.getInfoLabel('VideoPlayer.OriginalTitle') or xbmc.getInfoLabel('VideoPlayer.Title')
    year = xbmc.getInfoLabel('VideoPlayer.Year')
    if kind == 'episode':
        year = ''  # an episode's year is not the year the show started
    title = (title or '').strip()
    if '://' in title or title.lower().endswith(('.mkv', '.mp4', '.avi', '.ts', '.strm')):
        return '', ''  # a file name, not a title
    return title, year if year.isdigit() else ''


# ---------------------------------------------------------------- original language lookup

def from_tmdb(ids, kind, key):
    base = 'https://api.themoviedb.org/3/'
    tv = kind in ('episode', 'tvshow', 'season')
    if ids.get('tmdb'):
        d = get_json(base + '%s/%s?api_key=%s' % ('tv' if tv else 'movie', ids['tmdb'], key))
        return [d.get('original_language')]
    for src, val in (('imdb_id', ids.get('imdb')), ('tvdb_id', ids.get('tvdb'))):
        if not val:
            continue
        d = get_json(base + 'find/%s?external_source=%s&api_key=%s' % (val, src, key))
        for r in d.get('movie_results', []) + d.get('tv_results', []):
            return [r.get('original_language')]
        for r in d.get('tv_episode_results', []):
            return [get_json(base + 'tv/%s?api_key=%s' % (r['show_id'], key)).get('original_language')]
    return []


def tmdb_by_title(title, year, kind, key):
    tv = kind in ('episode', 'tvshow', 'season')
    url = 'https://api.themoviedb.org/3/search/%s?api_key=%s&query=%s' % (
        'tv' if tv else 'movie', key, quote(title))
    if year:
        url += '&%s=%s' % ('first_air_date_year' if tv else 'year', year)
    results = get_json(url).get('results') or []
    return [results[0].get('original_language')] if results else []


def wikidata_by_title(title, year, kind):
    """Original language of the best known film or series with this name. Only items with an
    IMDb id count, so a book or a person with the same name is not taken."""
    found = get_json('https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&'
                     'language=en&type=item&limit=7&search=' + quote(title)).get('search') or []
    qids = ' '.join('wd:%s' % f['id'] for f in found if f.get('id'))
    if not qids:
        return []
    q = ('SELECT ?i ?c ?d WHERE { VALUES ?i { %s } ?i wdt:P345 ?imdb . ?i wdt:P364 ?l . '
         '?l wdt:P218 ?c . OPTIONAL { ?i wdt:P577|wdt:P580 ?d } }') % qids
    rows = get_json('https://query.wikidata.org/sparql?format=json&query=' + quote(q),
                    timeout=12).get('results', {}).get('bindings', [])
    order = [f['id'] for f in found]
    best = []
    for r in rows:
        qid = r['i']['value'].rsplit('/', 1)[-1]
        y = (r.get('d', {}).get('value') or '')[:4]
        score = (bool(year) and y != year, order.index(qid) if qid in order else 99)
        best.append((score, r['c']['value']))
    best.sort()
    return [best[0][1]] if best else []


def from_wikidata(ids, kind):
    tv = kind in ('episode', 'tvshow', 'season')
    match = []
    if ids.get('imdb'):
        match.append('{ ?i wdt:P345 "%s" }' % ids['imdb'])
    if ids.get('tmdb'):
        match.append('{ ?i wdt:%s "%s" }' % ('P4983' if tv else 'P4947', ids['tmdb']))
    if ids.get('tvdb') and tv:
        match.append('{ ?i wdt:P4835 "%s" }' % ids['tvdb'])
    if not match:
        return []
    # The item's own original language, or the one of the series an episode belongs to
    q = ('SELECT DISTINCT ?c WHERE { %s '
         '{ ?i wdt:P364 ?l } UNION { ?i wdt:P179 ?s . ?s wdt:P364 ?l } UNION { ?i wdt:P361 ?s . ?s wdt:P364 ?l } '
         '?l wdt:P218 ?c } LIMIT 5') % ' UNION '.join(match)
    d = get_json('https://query.wikidata.org/sparql?format=json&query=' + quote(q), timeout=12)
    return [b['c']['value'] for b in d.get('results', {}).get('bindings', [])]


def load_cache():
    try:
        with open(CACHE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, 'w') as fh:
            json.dump(cache, fh)
    except OSError as e:
        log('cache not saved: %s' % e, xbmc.LOGWARNING)


def original_languages(ids, kind, title='', year=''):
    if ids:
        key = '|'.join('%s=%s' % kv for kv in sorted(ids.items()))
    else:
        key = 'title=%s|year=%s|%s' % (title.lower(), year, kind)
    cache = load_cache()
    hit = cache.get(key)
    if hit and time.time() - hit.get('t', 0) < CACHE_DAYS * 86400:
        return hit['langs']
    langs = []
    api_key = addon().getSettingString('tmdb_key').strip()
    if ids:
        sources = ([('TMDb', lambda: from_tmdb(ids, kind, api_key))] if api_key else []) + \
                  [('Wikidata', lambda: from_wikidata(ids, kind))]
    else:
        sources = ([('TMDb title search', lambda: tmdb_by_title(title, year, kind, api_key))]
                   if api_key else []) + \
                  [('Wikidata title search', lambda: wikidata_by_title(title, year, kind))]
    for name, fn in sources:
        try:
            langs = [l for l in fn() if l]
        except Exception as e:
            log('%s lookup failed: %s' % (name, e), xbmc.LOGWARNING)
            continue
        log('%s: original language of %s = %s' % (name, key, langs))
        if langs:
            break
    if langs:
        cache[key] = {'langs': langs, 't': time.time()}
        save_cache(cache)
    return langs


# ---------------------------------------------------------------- picking the track

def audio_streams():
    players = rpc('Player.GetActivePlayers')
    players = players if isinstance(players, list) else []
    pid = next((p['playerid'] for p in players if p.get('type') == 'video'), 1)
    res = rpc('Player.GetProperties', {'playerid': pid, 'properties': ['audiostreams', 'currentaudiostream']})
    return res.get('audiostreams') or [], res.get('currentaudiostream') or {}


def score(s):
    name = (s.get('name') or '').lower()
    bad = any(w in name for w in ('commentary', 'comment', 'description', 'descriptive', 'audio description'))
    return (not bad, not s.get('isimpaired', False), s.get('isdefault', False), s.get('channels', 0))


def choose(streams, langs):
    wanted = [lang_name(l) for l in langs]
    for w in wanted:
        same = [s for s in streams if w and lang_name(s.get('language')) == w]
        if same:
            return max(same, key=score), w
    flagged = [s for s in streams if s.get('isoriginal')]
    if flagged:
        return max(flagged, key=score), 'flagged as original'
    return None, None


class Player(xbmc.Player):
    def __init__(self):
        super().__init__()
        self.pending = 0
        self.tries = 0
        self.holding = False

    def onAVStarted(self):
        if self.isPlayingVideo() and addon().getSettingBool('enabled'):
            self.pending = time.time()
            self.tries = 0
            if setting_on('hold_start'):
                # Optional: keep the video paused at its start until the track is chosen;
                # Subtitle Cycler can hold it at the same time for the subtitle
                hold.start('Original Audio', 15)
                self.holding = True

    def onPlayBackStopped(self):
        hold.stopped()

    def onPlayBackEnded(self):
        hold.stopped()


def handle(player):
    ids, kind = playing_ids(player)
    streams, current = audio_streams()
    if len(streams) < 2:
        return  # nothing to choose from
    title, year = ('', '') if ids else playing_title(kind)
    log('playing %s %s, %d audio tracks, current: %s' % (
        kind, ids or 'no ids, title "%s"' % title, len(streams), current.get('language')))
    langs = original_languages(ids, kind, title, year) if (ids or title) else []
    best, why = choose(streams, langs)
    if not best:
        log('no matching track for %s' % langs)
        return not langs  # nothing known yet: worth another try

    if best.get('index') == current.get('index'):
        log('already on original audio (%s)' % why)
        return
    if not player.isPlayingVideo():
        return
    player.setAudioStream(best['index'])
    log('switched to track %d %s (%s)' % (best['index'], best.get('language'), why))
    if addon().getSettingBool('notify'):
        label = lang_name(best.get('language')) or best.get('language') or '?'
        name = best.get('name') or ''
        if name and name.lower() != label.lower():
            label = '%s - %s' % (label, name)
        xbmcgui.Dialog().notification('Original Audio', label, xbmcgui.NOTIFICATION_INFO, 3000)


def run():
    monitor = xbmc.Monitor()
    player = Player()
    log('service started')
    while not monitor.waitForAbort(0.5):
        # Run outside the player callback so the network lookup never blocks Kodi's player thread
        if player.pending and time.time() - player.pending > 1:
            player.pending = 0
            try:
                again = handle(player)
            except Exception as e:
                log('failed: %s' % e, xbmc.LOGWARNING)
                again = True
            # Other add-ons may give the video its ids a bit later (or the network was slow):
            # look again a few times while it plays
            if again and player.tries < 3 and player.isPlayingVideo():
                player.tries += 1
                player.pending = time.time() + 15
            if player.holding:
                # later tries happen while the video plays: let it go after the first one
                player.holding = False
                hold.release('Original Audio')
        hold.check()


run()
