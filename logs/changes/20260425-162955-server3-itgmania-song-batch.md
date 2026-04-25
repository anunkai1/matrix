# Server3 ITGmania Requested Song Batch

- Time: 2026-04-25 16:29 AEST
- Installed requested ZIv pad simfiles under `/opt/itgmania/Songs/V`:
  - `Gangnam Style` / Psy (`19558`)
  - `Despacito` / Luis Fonsi ft. Daddy Yankee (`48516`)
  - `Say So` / Doja Cat (`47891`)
  - `Chandelier` / Sia (`27525`)
  - `1 2 Step (DDR Cut)` / Ciara ft. Missy Elliott (`42518`)
  - `Listen To Your Heart (Furious F EZ Radio Edit)` / D.H.T. feat. Edmee (`478`)
  - `Boom Boom Boom Boom! (Eurobeat Mix)` / Vengaboys (`65060`)
  - `CINEMA (SKRILLEX REMIX)` / Benny Benassi feat. Gary Go (`23664`)
  - `Call Me Maybe` / Carly Rae Jepsen (`19451`)
  - `Whistle` / Flo Rida (`20600`)
  - `Starboy` / The Weeknd feat. Daft Punk (`31387`)
- Removed optional video files from `/opt/itgmania/Songs/V` after the batch because the TV launch path became slow during media initialization; chart, audio, banner, jacket, and background assets remain installed.
- Restarted ITGmania with `bash ops/tv-desktop/server3-tv-itgmania.sh --restart`; relaunched PID was `119896`.
- Verified `/home/tv/.itgmania/Logs/log.txt` loaded `20` songs from `Songs/V`, including the newly installed titles.
