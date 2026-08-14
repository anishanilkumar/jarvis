{ config, lib, ... }:
{
  # Home Assistant — the device and media layer behind Jarvis.
  #
  # It is deliberately NOT the dashboard framework. Two reasons: HA Assist has
  # no speaker recognition, which the voice pipeline needs; and Lovelace fights
  # a bespoke ambient layout. Jarvis owns the display and the intent registry;
  # HA owns devices, and relays `command_activity` to the tablet's Companion
  # App to launch YouTube Music with the existing Premium account.
  #
  # Tailnet-only, like Stash and the *arr stack — this is an admin surface, not
  # something the household or LAN guests should reach.
  #
  # RAM note: HA wants roughly 0.5-1 GB. On this Pi 4, already running Jellyfin,
  # Stash, Whisparr/Prowlarr, qBittorrent, an X desktop and noVNC, check
  # `free -h` before and after enabling. If it is tight, cut
  # `extraComponents` further rather than reaching for swap — swap on the SSD
  # is what historically caused the under-voltage dips (see
  # an under-voltage logger).

  services.home-assistant = {
    enable = true;

    # Only what's actually used. Every component costs startup time and
    # resident memory, and the default set pulls in a great deal that this
    # household has no hardware for.
    extraComponents = [
      "default_config"
      "met"              # weather, for HA's own automations
      "mobile_app"       # the Companion App — required for command_activity
      "cast"             # Chromecast, if one ever appears
      "jellyfin"         # media already on this box
      "conversation"     # the endpoint Jarvis falls through to for device commands
    ];

    config = {
      default_config = { };

      homeassistant = {
        name = "Home";
        unit_system = "metric";
        time_zone = "Europe/Berlin";
        country = "DE";
      };

      # Behind Caddy on the tailnet address, so HA must trust that proxy or it
      # rejects every request as coming from an untrusted host.
      http = {
        server_host = [ "127.0.0.1" ];
        server_port = 8123;
        use_x_forwarded_for = true;
        trusted_proxies = [ "127.0.0.1" "::1" ];
      };
    };
  };
}
