{
  lib,
  stdenvNoCC,
  makeWrapper,
  coreutils,
  gnugrep,
  python3,
}:
let
  python = python3.withPackages (ps: [
    ps.pygobject3
    ps.pyudev
  ]);
in
stdenvNoCC.mkDerivation {
  pname = "hid-apple-studio-display-tools";
  version = builtins.head (
    builtins.match ''.*PACKAGE_VERSION="([^"]+)".*'' (builtins.readFile ../dkms.conf)
  );

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../contrib
      ../tests
      ../dkms.conf
    ];
  };
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 contrib/asd-als-role "$out/lib/udev/asd-als-role"
    install -Dm755 contrib/asd-bind-orientation "$out/lib/udev/asd-bind-orientation"
    for helper in asd-als-role asd-bind-orientation; do
      wrapProgram "$out/lib/udev/$helper" \
        --prefix PATH : ${
          lib.makeBinPath [
            coreutils
            gnugrep
          ]
        }
    done

    for helper in asd-autorotate asd-gnome-rescan; do
      install -Dm644 "contrib/$helper" "$out/libexec/$helper"
      makeWrapper ${python}/bin/python3 "$out/bin/$helper" \
        --add-flags "$out/libexec/$helper"
      install -Dm644 "contrib/$helper.service" "$out/lib/systemd/user/$helper.service"
      substituteInPlace "$out/lib/systemd/user/$helper.service" \
        --replace-fail "/usr/bin/env $helper" "$out/bin/$helper"
    done

    install -Dm644 contrib/90-hid-apple-studio-display.rules \
      "$out/lib/udev/rules.d/90-hid-apple-studio-display.rules"
    substituteInPlace "$out/lib/udev/rules.d/90-hid-apple-studio-display.rules" \
      --replace-fail /usr/lib/udev/ "$out/lib/udev/"

    runHook postInstall
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    # This imports Gio/GLib without needing hardware or a desktop session.
    "$out/bin/asd-autorotate" --help > /dev/null
    env -u DBUS_SESSION_BUS_ADDRESS "$out/bin/asd-gnome-rescan"
    ${python}/bin/python3 -m unittest discover -s tests
    ${python}/bin/python3 -c 'import pyudev'
    runHook postInstallCheck
  '';

  meta = {
    description = "Udev and GNOME helpers for the Apple Studio Display";
    homepage = "https://github.com/eva-val/hid-apple-studio-display";
    license = lib.licenses.gpl2Only;
    platforms = lib.platforms.linux;
  };
}
