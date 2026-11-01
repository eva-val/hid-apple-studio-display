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
  enabled = evaluate {
    hardware.apple-studio-display = {
      enable = true;
      connector = "DP-1";
      fadeMs = 150;
    };
  };
  customKernel = evaluate {
    boot.kernelPackages = pkgs.linuxPackages_latest;
    hardware.apple-studio-display = {
      enable = true;
      ambientLight.enable = true;
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
assert builtins.elem "hid-apple-studio-display" enabled.boot.kernelModules;
assert (driverFor enabled).kernel.modDirVersion == enabled.boot.kernelPackages.kernel.modDirVersion;
assert
  (driverFor customKernel).kernel.modDirVersion == pkgs.linuxPackages_latest.kernel.modDirVersion;
assert nixpkgs.lib.hasInfix "fade_ms=150 connector=DP-1" enabled.boot.extraModprobeConfig;
assert !(enabled.systemd.user.services ? asd-autorotate);
assert enabled.systemd.user.services.asd-gnome-rescan.after == [ "graphical-session.target" ];
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
    customKernel.environment.etc."systemd/user".source
  }/graphical-session.target.wants/asd-autorotate.service
  ! grep -q 'asd-bind-orientation\|asd-als-role' ${
    enabled.environment.etc."udev/rules.d".source
  }/99-local.rules
  grep -q 'asd-bind-orientation' ${customKernel.environment.etc."udev/rules.d".source}/99-local.rules
  grep -q 'asd-als-role' ${customKernel.environment.etc."udev/rules.d".source}/99-local.rules
  touch "$out"
''
