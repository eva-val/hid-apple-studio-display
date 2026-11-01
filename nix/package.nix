{
  lib,
  stdenv,
  kernel,
  kernelModuleMakeFlags,
}:
stdenv.mkDerivation {
  pname = "hid-apple-studio-display";
  version = builtins.head (
    builtins.match ''.*PACKAGE_VERSION="([^"]+)".*'' (builtins.readFile ../dkms.conf)
  );

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../Makefile
      ../dkms.conf
      ../hid-apple-studio-display.c
    ];
  };
  nativeBuildInputs = kernel.moduleBuildDependencies;
  hardeningDisable = [ "pic" ];

  postPatch = ''
    substituteInPlace Makefile \
      --replace-fail 'depmod -a $(KVER)' '$(DEPMOD) -a $(KVER)'
  '';

  makeFlags = kernelModuleMakeFlags ++ [
    "KVER=${kernel.modDirVersion}"
    "KDIR=${kernel.dev}/lib/modules/${kernel.modDirVersion}/build"
    "INSTALL_MOD_PATH=${placeholder "out"}"
    "INSTALL_MOD_DIR=extra"
    "DEPMOD=true"
  ];
  installTargets = [ "install" ];
  enableParallelBuilding = true;

  # Leave module stripping, compression and signing to the kernel build.
  dontStrip = true;
  dontPatchELF = true;

  passthru = { inherit kernel; };

  meta = {
    description = "Apple Studio Display backlight and orientation sensor driver";
    homepage = "https://github.com/eva-val/hid-apple-studio-display";
    license = lib.licenses.gpl2Only;
    platforms = lib.platforms.linux;
  };
}
