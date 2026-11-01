{
  nixpkgs,
  pkgs,
  module,
}:
let
  evaluate =
    settings:
    (nixpkgs.lib.nixosSystem {
      system = pkgs.stdenv.hostPlatform.system;
      modules = [
        module
        settings
        { system.stateVersion = "26.05"; }
      ];
    }).config;
  disabled = evaluate { };
  disabledWithLight = evaluate {
    hardware.apple-studio-display.ambientLight.enable = true;
  };
  orientationOnly = evaluate {
    hardware.apple-studio-display = {
      enable = true;
      orientation.enable = true;
    };
  };
  rotationOnly = evaluate {
    hardware.apple-studio-display = {
      enable = true;
      autoRotate.enable = true;
    };
  };
  disabledWithRotate = evaluate {
    hardware.apple-studio-display.autoRotate.enable = true;
  };
  gnomeWithoutLight = evaluate {
    services.desktopManager.gnome.enable = true;
    hardware.apple-studio-display.enable = true;
  };
  gnomeWithLight = evaluate {
    services.desktopManager.gnome.enable = true;
    hardware.apple-studio-display = {
      enable = true;
      ambientLight.enable = true;
    };
  };
  enabled = evaluate {
    hardware.apple-studio-display = {
      enable = true;
      connector = "DP-1";
      fadeMs = 150;
      displayMap = {
        "first-usb-serial" = "12345678";
        "second-usb-serial" = "87654321";
      };
    };
  };
  customKernel = evaluate {
    boot.kernelPackages = pkgs.linuxPackages_latest;
    hardware.apple-studio-display = {
      enable = true;
      ambientLight.enable = true;
      ambientLight.preferredSerial = "preferred-display";
      autoRotate = {
        enable = true;
        extraArgs = [
          "--axis"
          "x"
        ];
      };
    };
  };
  driverFor = config: builtins.head config.boot.extraModulePackages;
in
assert disabled.boot.extraModulePackages == [ ];
assert !(disabled.systemd.user.services ? asd-gnome-rescan);
assert !disabled.hardware.sensor.iio.enable;
assert !disabledWithLight.hardware.sensor.iio.enable;
assert disabledWithLight.nixpkgs.overlays == [ ];
assert !enabled.hardware.sensor.iio.enable;
assert enabled.nixpkgs.overlays == [ ];
assert !orientationOnly.hardware.sensor.iio.enable;
assert orientationOnly.nixpkgs.overlays == [ ];
assert !(nixpkgs.lib.hasInfix "ASD_ALS_ROLE" orientationOnly.services.udev.extraRules);
assert !(orientationOnly.systemd.user.services ? asd-autorotate);
assert nixpkgs.lib.hasInfix "asd-bind-orientation" orientationOnly.services.udev.extraRules;
assert !rotationOnly.hardware.sensor.iio.enable;
assert rotationOnly.nixpkgs.overlays == [ ];
assert rotationOnly.hardware.apple-studio-display.orientation.enable;
assert rotationOnly.systemd.user.services ? asd-autorotate;
assert nixpkgs.lib.hasInfix "asd-bind-orientation" rotationOnly.services.udev.extraRules;
assert !(nixpkgs.lib.hasInfix "ASD_ALS_ROLE" rotationOnly.services.udev.extraRules);
assert disabledWithRotate.boot.extraModulePackages == [ ];
assert !(disabledWithRotate.systemd.user.services ? asd-autorotate);
assert !(nixpkgs.lib.hasInfix "asd-bind-orientation" disabledWithRotate.services.udev.extraRules);
# GNOME may request the stock proxy for its own sensors independently of us.
assert gnomeWithoutLight.nixpkgs.overlays == [ ];
assert gnomeWithoutLight.hardware.sensor.iio.package.patches or [ ] == [ ];
assert builtins.length gnomeWithLight.nixpkgs.overlays == 1;
assert builtins.length gnomeWithLight.hardware.sensor.iio.package.patches > 0;
assert customKernel.nixpkgs.overlays == [ ];
assert builtins.elem "hid-apple-studio-display" enabled.boot.kernelModules;
assert (driverFor enabled).kernel.modDirVersion == enabled.boot.kernelPackages.kernel.modDirVersion;
assert
  (driverFor customKernel).kernel.modDirVersion == pkgs.linuxPackages_latest.kernel.modDirVersion;
assert nixpkgs.lib.hasInfix "fade_ms=150 connector=DP-1" enabled.boot.extraModprobeConfig;
assert nixpkgs.lib.hasInfix "display_map=first-usb-serial:12345678,second-usb-serial:87654321"
  enabled.boot.extraModprobeConfig;
assert !(enabled.systemd.user.services ? asd-autorotate);
assert customKernel.hardware.sensor.iio.enable;
assert builtins.length customKernel.hardware.sensor.iio.package.patches > 0;
assert nixpkgs.lib.hasInfix ''ENV{ASD_ALS_ROLE}=="single|front"''
  customKernel.services.udev.extraRules;
assert nixpkgs.lib.hasInfix ''ATTRS{serial}=="preferred-display"''
  customKernel.services.udev.extraRules;
assert nixpkgs.lib.hasInfix ''ENV{IIO_SENSOR_PROXY_LIGHT_SCALE}="0.001"''
  customKernel.services.udev.extraRules;
assert enabled.systemd.user.services.asd-gnome-rescan.after == [ "graphical-session.target" ];
assert enabled.systemd.user.services.asd-gnome-rescan.serviceConfig.Type == "simple";
assert nixpkgs.lib.hasSuffix " --watch"
  enabled.systemd.user.services.asd-gnome-rescan.serviceConfig.ExecStart;
assert !(nixpkgs.lib.hasInfix "SYSTEMD_USER_WANTS" enabled.services.udev.extraRules);
assert builtins.elem "graphical-session.target"
  customKernel.systemd.user.services.asd-autorotate.wantedBy;
assert nixpkgs.lib.hasInfix ''"--axis" "x"''
  customKernel.systemd.user.services.asd-autorotate.serviceConfig.ExecStart;
pkgs.runCommand "hid-apple-studio-display-module-check" { } ''
  # Force NixOS to assemble and validate rules and user units, including
  # absolute helper paths and the optional sensor/rotation integration.
  test -e ${enabled.environment.etc."udev/rules.d".source}/99-local.rules
  test -e ${customKernel.environment.etc."udev/rules.d".source}/99-local.rules
  test -e ${enabled.environment.etc."systemd/user".source}/asd-gnome-rescan.service
  test -e ${
    enabled.environment.etc."systemd/user".source
  }/graphical-session.target.wants/asd-gnome-rescan.service
  test -e ${
    customKernel.environment.etc."systemd/user".source
  }/graphical-session.target.wants/asd-autorotate.service
  ! grep -q 'asd-bind-orientation\|asd-als-role' ${
    enabled.environment.etc."udev/rules.d".source
  }/99-local.rules
  grep -q 'asd-bind-orientation' ${customKernel.environment.etc."udev/rules.d".source}/99-local.rules
  grep -q 'asd-als-role' ${customKernel.environment.etc."udev/rules.d".source}/99-local.rules
  touch "$out"
''
