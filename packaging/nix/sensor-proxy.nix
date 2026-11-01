{
  lib,
  iio-sensor-proxy,
  python3,
  umockdev,
  gobject-introspection,
  dbus,
}:
let
  python = python3.withPackages (ps: [
    ps.pygobject3
    ps.dbus-python
    ps.python-dbusmock
    ps.psutil
  ]);
in
iio-sensor-proxy.overrideAttrs (old: {
  patches = (old.patches or [ ]) ++ [ ../../patches/iio-sensor-proxy-ambient-light.patch ];
  postPatch = (old.postPatch or "") + ''
    patchShebangs tests
  '';
  nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
    python
    umockdev
    gobject-introspection
    dbus
  ];
  buildInputs = (old.buildInputs or [ ]) ++ [ umockdev ];
  mesonFlags = (old.mesonFlags or [ ]) ++ [ (lib.mesonBool "tests" true) ];
  doCheck = true;
  # These two upstream tests require a Qualcomm QRTR transport and also fail
  # unpatched in the Nix sandbox. Keep SSC support built, and run all other tests.
  checkPhase = ''
    runHook preCheck
    meson test --print-errorlogs \
      --exclude Tests.test_ssc_light --exclude Tests.test_ssc_compass
    runHook postCheck
  '';
})
