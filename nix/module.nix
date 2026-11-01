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
in
{
  options.hardware.apple-studio-display = {
    enable = lib.mkEnableOption "Apple Studio Display brightness and sensor support";

    connector = lib.mkOption {
      type = lib.types.nullOr (lib.types.strMatching "[A-Za-z0-9-]+");
      default = null;
      example = "DP-1";
      description = ''
        DRM connector for the display. Null uses driver auto-detection, which
        requires a single connected connector. Set this explicitly when other
        monitors or a laptop panel are connected.
      '';
    };

    fadeMs = lib.mkOption {
      type = lib.types.ints.between 0 65535;
      default = 0;
      example = 150;
      description = "Brightness transition time in milliseconds.";
    };

    ambientLight.enable = lib.mkEnableOption "front ambient light sensor selection and iio-sensor-proxy";

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
      }
    '';

    environment.systemPackages = [ tools ];
    assertions = [
      {
        assertion = !cfg.autoRotate.enable || cfg.orientation.enable;
        message = "Apple Studio Display auto-rotation requires orientation.enable.";
      }
    ];

    hardware.sensor.iio.enable = lib.mkIf cfg.ambientLight.enable (lib.mkDefault true);

    # Install only the requested integration rules. The standalone tools package
    # also ships the complete upstream rules for manual installation.
    services.udev.extraRules =
      lib.optionalString cfg.ambientLight.enable ''
        ACTION=="add|change", SUBSYSTEM=="iio", KERNELS=="0003:05AC:1114.*|0003:05AC:1116.*", ATTR{name}=="als", PROGRAM="${tools}/lib/udev/asd-als-role %p", RESULT=="rear", ENV{IIO_SENSOR_PROXY_TYPE}=""
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
