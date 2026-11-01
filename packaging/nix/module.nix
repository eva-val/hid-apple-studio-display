{
  config,
  lib,
  pkgs,
  utils,
  ...
}:
let
  cfg = config.hardware.apple-studio-display;
  driver = config.boot.kernelPackages.callPackage ./package.nix { };
  tools = pkgs.callPackage ./tools.nix { };
  sensorProxy = pkgs.callPackage ./sensor-proxy.nix { };
in
{
  options.hardware.apple-studio-display = {
    enable = lib.mkEnableOption "Apple Studio Display brightness and sensor support";

    connector = lib.mkOption {
      type = lib.types.nullOr (lib.types.strMatching "[A-Za-z0-9-]+");
      default = null;
      example = "DP-1";
      description = ''
        DRM connector override, such as DP-1 or card0-DP-1. Null detects a
        single Studio Display from EDID, ignoring other monitors and secondary
        tiles. Use displayMap for multiple Studio Displays.
      '';
    };

    displayMap = lib.mkOption {
      type = lib.types.attrsOf (lib.types.strMatching "[0-9a-fA-F]{8}");
      default = { };
      example = {
        "00008030-0011223344556677" = "1234abcd";
      };
      description = ''
        Map each display's USB serial to its eight-digit hexadecimal EDID serial.
        Run asd-detect with one physical Studio Display connected at a time to
        obtain pairs. This survives connector renumbering and takes precedence
        over connector. Every attached Studio Display needs an entry when set.
      '';
    };

    fadeMs = lib.mkOption {
      type = lib.types.ints.between 0 65535;
      default = 0;
      example = 150;
      description = "Brightness transition time in milliseconds.";
    };

    ambientLight.enable = lib.mkEnableOption "front ambient light sensor selection and iio-sensor-proxy";

    ambientLight.preferredSerial = lib.mkOption {
      type = lib.types.nullOr (lib.types.strMatching "[A-Za-z0-9-]+");
      default = null;
      description = ''
        USB serial of the preferred ambient-light source when multiple Studio
        Displays are connected. Other display sensors and then the laptop ALS
        remain fallbacks. GNOME consumes one shared ambient-light reading.
      '';
    };

    orientation.enable = lib.mkOption {
      type = lib.types.bool;
      default = cfg.autoRotate.enable;
      defaultText = lib.literalExpression "config.hardware.apple-studio-display.autoRotate.enable";
      description = "Rebind the orientation interface to this driver. Enabled automatically for auto-rotation.";
    };

    autoRotate.enable = lib.mkEnableOption "experimental GNOME auto-rotation for the display";

    autoRotate.extraArgs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [
        "--axis"
        "z"
        "--invert"
      ];
      description = "Additional arguments to asd-autorotate.";
    };
  };

  config = lib.mkIf cfg.enable {
    boot.extraModulePackages = [ driver ];
    boot.kernelModules = [ "hid-apple-studio-display" ];
    boot.extraModprobeConfig = ''
      options hid-apple-studio-display fade_ms=${toString cfg.fadeMs}${
        lib.optionalString (cfg.connector != null) " connector=${cfg.connector}"
      }${
        lib.optionalString (cfg.displayMap != { }) (
          " display_map="
          + lib.concatStringsSep "," (lib.mapAttrsToList (serial: edid: "${serial}:${edid}") cfg.displayMap)
        )
      }
    '';

    environment.systemPackages = [ tools ];
    assertions = [
      {
        assertion =
          builtins.length (builtins.attrNames cfg.displayMap) <= 16
          && lib.all (serial: builtins.match "[A-Za-z0-9-]+" serial != null) (
            builtins.attrNames cfg.displayMap
          )
          && lib.all (edid: edid != "00000000") (builtins.attrValues cfg.displayMap)
          &&
            builtins.length (lib.unique (map lib.toLower (builtins.attrValues cfg.displayMap)))
            == builtins.length (builtins.attrNames cfg.displayMap);
        message = "Apple Studio Display displayMap requires at most 16 USB serials and unique nonzero EDID serials.";
      }
      {
        assertion = !cfg.autoRotate.enable || cfg.orientation.enable;
        message = "Apple Studio Display auto-rotation requires orientation.enable.";
      }
    ];

    hardware.sensor.iio.enable = lib.mkIf cfg.ambientLight.enable (lib.mkDefault true);
    hardware.sensor.iio.package = lib.mkIf cfg.ambientLight.enable sensorProxy;

    nixpkgs.overlays =
      lib.mkIf (cfg.ambientLight.enable && config.services.desktopManager.gnome.enable)
        [
          (_final: prev: {
            gnome-settings-daemon = prev.gnome-settings-daemon.overrideAttrs (old: {
              patches = (old.patches or [ ]) ++ [ ../../patches/gnome-settings-daemon-reclaim-light.patch ];
            });
          })
        ];

    # Install only the requested integration rules. The standalone tools package
    # also ships the complete upstream rules for manual installation.
    services.udev.extraRules =
      lib.optionalString cfg.ambientLight.enable ''
        ACTION=="add|change", SUBSYSTEM=="iio", KERNELS=="0003:05AC:1114.*|0003:05AC:1116.*", ATTR{name}=="als", PROGRAM="${tools}/lib/udev/asd-als-role %p", ENV{ASD_ALS_ROLE}="%c"
        ACTION=="add|change", SUBSYSTEM=="iio", ENV{ASD_ALS_ROLE}=="rear", ENV{IIO_SENSOR_PROXY_TYPE}=""
        ACTION=="add|change", SUBSYSTEM=="iio", ENV{ASD_ALS_ROLE}=="single|front", ENV{IIO_SENSOR_PROXY_LIGHT_PRIORITY}="100", ENV{IIO_SENSOR_PROXY_LIGHT_SCALE}="0.001"
        # Re-evaluate siblings once both sensors have finished enumerating.
        ACTION=="add", SUBSYSTEM=="iio", ENV{ASD_ALS_ROLE}=="single|front|rear", RUN+="${pkgs.systemd}/bin/udevadm trigger --action=change --subsystem-match=iio"
      ''
      + lib.optionalString (cfg.ambientLight.enable && cfg.ambientLight.preferredSerial != null) ''
        ACTION=="add|change", SUBSYSTEM=="iio", ENV{ASD_ALS_ROLE}=="single|front", ATTRS{serial}=="${cfg.ambientLight.preferredSerial}", ENV{IIO_SENSOR_PROXY_LIGHT_PRIORITY}="200"
      ''
      + lib.optionalString cfg.orientation.enable ''
        ACTION=="add", SUBSYSTEM=="hid", ENV{MODALIAS}=="hid:b0003g0003v000005ACp0000111[46]", RUN+="${tools}/lib/udev/asd-bind-orientation %k"
      '';

    systemd.user.services.asd-gnome-rescan = {
      description = "Discover the Apple Studio Display brightness control in GNOME";
      partOf = [ "graphical-session.target" ];
      after = [ "graphical-session.target" ];
      wantedBy = [ "graphical-session.target" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = "${tools}/bin/asd-gnome-rescan --watch";
        Restart = "on-failure";
        RestartSec = 5;
      };
    };

    systemd.user.services.asd-autorotate = lib.mkIf cfg.autoRotate.enable {
      description = "Rotate the Apple Studio Display with its orientation sensor";
      partOf = [ "graphical-session.target" ];
      after = [ "graphical-session.target" ];
      wantedBy = [ "graphical-session.target" ];
      serviceConfig = {
        ExecStart = utils.escapeSystemdExecArgs (
          [ "${tools}/bin/asd-autorotate" ] ++ cfg.autoRotate.extraArgs
        );
        Restart = "on-failure";
        RestartSec = 5;
      };
    };
  };
}
