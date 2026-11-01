{
  pkgs ? import <nixpkgs> { },
  kernelPackages ? pkgs.linuxPackages,
}:
kernelPackages.callPackage ./packaging/nix/package.nix { }
