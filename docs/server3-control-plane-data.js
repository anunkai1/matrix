window.SERVER3_CONTROL_PLANE_DATA = {
  "generatedAt": "2026-06-03T06:53:35.532172+10:00",
  "timezone": "Australia/Brisbane",
  "defaultRuntime": "architect",
  "summary": {
    "runtimeValue": "6 live",
    "runtimeCopy": "5 healthy, 1 degraded, 0 waiting, 0 offline",
    "approvalValue": "0 pending",
    "approvalCopy": "explicit human gates from live Server3 state",
    "jobValue": "12 tracked",
    "jobCopy": "timers, approvals, and operator playback in one surface",
    "hostValue": "load 4.82 / ram 8%",
    "hostCopy": "browser, timers, storage, and network summarized from the host",
    "currentPicture": [
      "03 Jun 2026 06:53 AEST",
      "snapshot file server3-control-plane-data.js",
      "0 approval item(s)"
    ],
    "surfaceBias": [
      "read-only live snapshot",
      "browser-local file:// compatible",
      "state color only"
    ],
    "chips": [
      {
        "tone": "ok",
        "label": "live status loaded"
      },
      {
        "tone": "busy",
        "label": "observer summary"
      },
      {
        "tone": "warn",
        "label": "0 approval item(s)"
      },
      {
        "tone": "busy",
        "label": "8 operator actions"
      },
      {
        "tone": "danger",
        "label": "storage remains continuity sensitive"
      }
    ]
  },
  "overview": {
    "bands": [
      {
        "title": "Nominal lane",
        "stateClass": "ok",
        "stateText": "healthy",
        "body": "5 selected runtimes match expected live posture."
      },
      {
        "title": "Approval lane",
        "stateClass": "ok",
        "stateText": "clear",
        "body": "0 operator approval item(s) currently surfaced."
      },
      {
        "title": "Watch lane",
        "stateClass": "ok",
        "stateText": "clear",
        "body": "No selected runtime is currently off its default expected posture."
      },
      {
        "title": "Offline lane",
        "stateClass": "ok",
        "stateText": "none",
        "body": "0 selected runtime(s) are currently offline."
      }
    ],
    "side": [
      {
        "label": "service footprint",
        "value": "6",
        "copy": "selected runtimes in the operator rail"
      },
      {
        "label": "operator gates",
        "value": "0",
        "copy": "explicit human approvals, not implicit risk"
      }
    ]
  },
  "activity": [
    {
      "time": "06:54:13",
      "title": "Oracle recent service activity",
      "channel": "signal runtime",
      "statusClass": "danger",
      "statusText": "degraded",
      "copy": "2026-06-03 06:54:13,293 WARNING Signal event stream failed: <urlopen error [Errno 111] Connection refused>"
    },
    {
      "time": "06:54:06",
      "title": "Tank recent service activity",
      "channel": "telegram sibling",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.started"
    },
    {
      "time": "06:54:04",
      "title": "Mavali ETH recent service activity",
      "channel": "venue operations runtime",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.started"
    },
    {
      "time": "06:53:58",
      "title": "Diary recent service activity",
      "channel": "capture runtime",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.started"
    },
    {
      "time": "06:53:55",
      "title": "Architect recent service activity",
      "channel": "telegram primary",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "bridge.started"
    },
    {
      "time": "19:09:44",
      "title": "Govorun recent service activity",
      "channel": "whatsapp runtime",
      "statusClass": "ok",
      "statusText": "healthy",
      "copy": "Started whatsapp-govorun-bridge.service - WhatsApp Govorun Bridge (Codex)."
    }
  ],
  "playback": {
    "items": [
      {
        "time": "20:53:41",
        "title": "refreshed control-plane snapshot",
        "channel": "snapshot",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "snapshot refresh via local. /home/architect/matrix/docs/server3-control-plane-data.json"
      },
      {
        "time": "20:25:29",
        "title": "refreshed control-plane snapshot",
        "channel": "snapshot",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "snapshot refresh via local. /home/architect/matrix/docs/server3-control-plane-data.json"
      },
      {
        "time": "21:42:58",
        "title": "SignalTube rescan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube rescan via token. signaltube-lab-rescan.service"
      },
      {
        "time": "21:39:40",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via token. show me some videos from the last 3 days on cryptocurrency"
      },
      {
        "time": "21:31:48",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via token. I want to watch about science"
      },
      {
        "time": "21:01:28",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via token. I want to see videos about philosophy"
      },
      {
        "time": "20:48:17",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via local. I want to see videos about AI news, but not from MSM"
      },
      {
        "time": "20:39:35",
        "title": "Ask SignalTube scan started",
        "channel": "signaltube",
        "statusClass": "ok",
        "statusText": "ok",
        "copy": "signaltube ask via token. I want to see videos about AI news, but not from MSM"
      }
    ],
    "meta": [
      {
        "label": "recent operator actions",
        "value": "8"
      },
      {
        "label": "last actor path",
        "value": "local"
      },
      {
        "label": "last action",
        "value": "snapshot refresh"
      },
      {
        "label": "captured bundles",
        "value": "1"
      }
    ],
    "bundles": [
      {
        "label": "incident-bundle-20260401T005358.json",
        "value": "01 Apr 00:53 / 94 KiB"
      }
    ]
  },
  "approvals": [],
  "jobs": [
    {
      "title": "Observer summary",
      "tagClass": "busy",
      "tagText": "03 Jun 06:55",
      "body": "server3-runtime-observer.timer is active(waiting). Last trigger: 03 Jun 06:50."
    },
    {
      "title": "Routing drift check",
      "tagClass": "busy",
      "tagText": "04 Jun 06:15",
      "body": "server3-chat-routing-contract-check.timer is active(waiting). Last trigger: 03 Jun 06:15."
    },
    {
      "title": "State backup",
      "tagClass": "busy",
      "tagText": "01 Jul 05:00",
      "body": "server3-state-backup.timer is active(waiting). Last trigger: 01 Jun 05:00."
    },
    {
      "title": "Receipt monitor",
      "tagClass": "busy",
      "tagText": "not scheduled",
      "body": "mavali-eth-receipt-monitor.timer is active(waiting). Last trigger: 03 Jun 06:39."
    }
  ],
  "floor": [
    {
      "title": "Internal disk",
      "stateClass": "ok",
      "stateText": "nominal",
      "value": "13% used",
      "body": "/ | 393 GiB free of 480 GiB",
      "statusLine": "system root filesystem"
    },
    {
      "title": "External disk",
      "stateClass": "warn",
      "stateText": "watch",
      "value": "missing",
      "body": "/srv/external/server3-arr | path unavailable",
      "statusLine": "backup disk: 7% used"
    },
    {
      "title": "Host health",
      "stateClass": "ok",
      "stateText": "nominal",
      "value": "load 4.82 / ram 8%",
      "body": "primary route eno2 / 192.168.0.148",
      "statusLine": "host: server3"
    },
    {
      "title": "Key paths",
      "stateClass": "busy",
      "stateText": "live",
      "value": "/data/downloads",
      "body": "13% used | 393 GiB free of 480 GiB",
      "statusLine": "canonical media namespace is /data/downloads and /data/media/..."
    },
    {
      "title": "Schedules",
      "stateClass": "busy",
      "stateText": "queued",
      "value": "Observer summary, Routing drift check, State backup",
      "body": "Visible timers stay on the floor so continuity work is never hidden behind another tool.",
      "statusLine": "next: 03 Jun 06:55"
    }
  ],
  "runtimes": [
    {
      "key": "architect",
      "name": "Architect",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "Telegram primary",
      "operatorNote": "owner-facing runtime",
      "summary": "Main Telegram and CLI runtime for Server3 operations.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "telegram-architect-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/architect/matrix"
        },
        {
          "label": "owner",
          "value": "architect"
        },
        {
          "label": "live state",
          "value": "active"
        }
      ],
      "recentJobs": [
        {
          "label": "telegram-architect-bridge.service",
          "value": "20:28:21 Expired 1 idle Pi RPC session(s) after 900s timeout."
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Primary operator entry point on Server3."
        },
        {
          "label": "change control",
          "value": "persistent repo edits still require commit and push proof"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u telegram-architect-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/telegram-architect-bridge.md"
        },
        {
          "label": "policy",
          "value": "ARCHITECT_INSTRUCTION.md"
        }
      ],
      "unitNames": [
        "telegram-architect-bridge.service"
      ],
      "auditTrail": [
        {
          "label": "10 Apr 23:14 / runtime logs",
          "value": "ok via local | telegram-architect-bridge.service"
        },
        {
          "label": "10 Apr 23:14 / runtime logs",
          "value": "ok via local | telegram-architect-bridge.service"
        },
        {
          "label": "10 Apr 23:12 / runtime restart",
          "value": "ok via local | telegram-architect-bridge.service"
        }
      ]
    },
    {
      "key": "tank",
      "name": "Tank",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "Telegram sibling",
      "operatorNote": "isolated Telegram runtime",
      "summary": "Sibling Telegram assistant with isolated runtime state.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "telegram-tank-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/tank/tankbot"
        },
        {
          "label": "owner",
          "value": "tank"
        },
        {
          "label": "live state",
          "value": "active"
        }
      ],
      "recentJobs": [
        {
          "label": "telegram-tank-bridge.service",
          "value": "04:52:49 bridge.telegram_api_retry_succeeded | getUpdates"
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Uses the shared bridge pattern with its own workspace and memory."
        },
        {
          "label": "identity",
          "value": "preserve isolated runtime root and Joplin profile"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u telegram-tank-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/runtime_docs/tank"
        },
        {
          "label": "runbook",
          "value": "ops/runtime_personas/check_runtime_repo_links.sh"
        }
      ],
      "unitNames": [
        "telegram-tank-bridge.service"
      ],
      "auditTrail": []
    },
    {
      "key": "diary",
      "name": "Diary",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "capture runtime",
      "operatorNote": "capture-focused sibling",
      "summary": "Dedicated Telegram diary assistant for low-friction text, voice, and photo capture.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "telegram-diary-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/diary/diarybot"
        },
        {
          "label": "owner",
          "value": "diary"
        },
        {
          "label": "live state",
          "value": "active"
        }
      ],
      "recentJobs": [
        {
          "label": "telegram-diary-bridge.service",
          "value": "06:53:58 bridge.started"
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Runs the shared Telegram bridge with its own runtime root, AGENTS.md, and diary-oriented operating docs."
        },
        {
          "label": "delivery",
          "value": "capture routing should stay friction-light"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u telegram-diary-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/runtime_docs/diary"
        },
        {
          "label": "policy",
          "value": "docs/runtime_docs/diary/DIARY_INSTRUCTION.md"
        }
      ],
      "unitNames": [
        "telegram-diary-bridge.service"
      ],
      "auditTrail": []
    },
    {
      "key": "govorun",
      "name": "Govorun",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "WhatsApp runtime",
      "operatorNote": "dual transport + bridge",
      "summary": "WhatsApp transport/API runtime used by the Govorun bridge.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "whatsapp-govorun-bridge.service, govorun-whatsapp-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/govorun/whatsapp-govorun/app"
        },
        {
          "label": "owner",
          "value": "govorun"
        },
        {
          "label": "live state",
          "value": "active / active"
        }
      ],
      "recentJobs": [
        {
          "label": "whatsapp-govorun-bridge.service",
          "value": "19:09:44 Started whatsapp-govorun-bridge.service - WhatsApp Govorun Bridge (Codex)."
        },
        {
          "label": "govorun-whatsapp-bridge.service",
          "value": "06:53:49 bridge.started"
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Node transport sidecar for the Python Govorun bridge."
        },
        {
          "label": "routing contract",
          "value": "daily contract drift timer should stay green"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u whatsapp-govorun-bridge.service -u govorun-whatsapp-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/runbooks/whatsapp-govorun-operations.md"
        },
        {
          "label": "guard",
          "value": "ops/chat-routing/validate_chat_routing_contract.py"
        }
      ],
      "unitNames": [
        "whatsapp-govorun-bridge.service",
        "govorun-whatsapp-bridge.service"
      ],
      "auditTrail": []
    },
    {
      "key": "oracle",
      "name": "Oracle",
      "stateClass": "danger",
      "stateText": "degraded",
      "role": "Signal runtime",
      "operatorNote": "transport + bridge",
      "summary": "Signal transport sidecar used by the Oracle bridge.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "signal-oracle-bridge.service, oracle-signal-bridge.service"
        },
        {
          "label": "workspace",
          "value": "/home/oracle/signal-oracle/app"
        },
        {
          "label": "owner",
          "value": "oracle"
        },
        {
          "label": "live state",
          "value": "deactivating / activating"
        }
      ],
      "recentJobs": [
        {
          "label": "signal-oracle-bridge.service",
          "value": "06:54:06 2026-06-03 06:54:03,292 WARNING Signal event stream failed: <urlopen error [Errno 111] Connection refused>"
        },
        {
          "label": "oracle-signal-bridge.service",
          "value": "06:53:33 Starting oracle-signal-bridge.service - Oracle Signal Bridge..."
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "expected active, got deactivating"
        },
        {
          "label": "operator note",
          "value": "Transport sidecar for the Oracle Signal runtime."
        },
        {
          "label": "voice path",
          "value": "keep local transcription runtime separate from transport health"
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u signal-oracle-bridge.service -u oracle-signal-bridge.service"
        },
        {
          "label": "docs",
          "value": "docs/runbooks/oracle-signal-operations.md"
        },
        {
          "label": "voice",
          "value": "ops/telegram-voice/transcribe_voice.sh"
        }
      ],
      "unitNames": [
        "signal-oracle-bridge.service",
        "oracle-signal-bridge.service"
      ],
      "auditTrail": []
    },
    {
      "key": "mavali",
      "name": "Mavali ETH",
      "stateClass": "ok",
      "stateText": "healthy",
      "role": "venue operations runtime",
      "operatorNote": "owner-bound wallet runtime",
      "summary": "Wallet-first Ethereum mainnet runtime with deterministic wallet actions and Codex fallback for non-wallet prompts.",
      "actions": [
        "restart runtime",
        "show recent logs",
        "refresh snapshot"
      ],
      "serviceStats": [
        {
          "label": "unit set",
          "value": "telegram-mavali-eth-bridge.service, mavali-eth-receipt-monitor.timer"
        },
        {
          "label": "workspace",
          "value": "/home/architect/gitea-server2/mavali_eth"
        },
        {
          "label": "owner",
          "value": "mavali_eth"
        },
        {
          "label": "live state",
          "value": "mixed"
        }
      ],
      "recentJobs": [
        {
          "label": "telegram-mavali-eth-bridge.service",
          "value": "06:54:04 bridge.started"
        },
        {
          "label": "mavali-eth-receipt-monitor.timer",
          "value": "19:09:35 Started mavali-eth-receipt-monitor.timer - Poll for confirmed inbound ETH for mavali_eth."
        }
      ],
      "watchouts": [
        {
          "label": "current issue",
          "value": "no active unit mismatch detected"
        },
        {
          "label": "operator note",
          "value": "Runs the shared Telegram bridge with the mavali_eth deterministic wallet engine plus Codex fallback for non-wallet prompts."
        }
      ],
      "docsAndLogs": [
        {
          "label": "logs",
          "value": "journalctl -u telegram-mavali-eth-bridge.service"
        },
        {
          "label": "docs",
          "value": "/home/architect/gitea-server2/mavali_eth/docs/mavali-eth-operations.md"
        },
        {
          "label": "guard",
          "value": "bridge-side pending-action guard"
        }
      ],
      "unitNames": [
        "telegram-mavali-eth-bridge.service",
        "mavali-eth-receipt-monitor.timer"
      ],
      "auditTrail": []
    }
  ]
};
