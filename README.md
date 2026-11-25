# GM Soundboard

Саундборд із гарячими клавішами для майстра НРІ. Дві стартові дошки: **Night City**
(Cyberpunk 2077) і **Elysium** (Vampire: The Masquerade), 12 слотів на дошку,
24 звуки CC0 у комплекті.

| Папка | Що всередині |
|---|---|
| [`desktop/`](desktop/) | програма для Windows (Python, pygame, pywebview) з **глобальними** хоткеями; `build.bat` збирає `.exe` |
| [`web/`](web/) | веб-версія для Cloudflare Workers (Web Audio, хоткеї у вкладці); `deploy.cmd` публікує |
| [`tools/soundpack/`](tools/soundpack/) | скрипти, що зібрали стартові звуки: частина з CC0-наборів, частина синтезована |

Інтерфейс спільний: `desktop/ui/` — єдине джерело, `web/build.py` копіює його у `web/public/`.

## Звуки
Усі стартові звуки — CC0 (суспільне надбання), список джерел: `web/public/sounds/starter/CREDITS.txt`.
Використано набори [Meta Open Sound](https://github.com/facebookincubator/meta-open-sound),
[Open Sleep Sounds](https://github.com/localhostnick/open-sleep-sounds),
[SFX Kit](https://github.com/wyzowl/sfx-kit); постріли, вибух, сирена, дзвін, серцебиття
та інше синтезовано в `tools/soundpack/synth.py`.
