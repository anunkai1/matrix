1. pytest is under .venv/server3-qa/bin/pytest.
2. ARR stack moved to server2 (2026-06-01). Sonarr/Radarr/Prowlarr/qBittorrent/Jellyfin/Jellyseerr all run there. Server3 has none. Server2 Sonarr API: http://192.168.0.118:8989 key=b57a1c1e420d426780164ba002dfd820.
3. TTS capable: use ops/telegram-voice/tts_english.sh to generate OGG voice notes (Microsoft Edge TTS, JennyNeural voice, 1.35x speed). Deliver via Telegram bridge with inline directive: [[audio_as_voice]] [[media: /path/to/file.ogg]].
