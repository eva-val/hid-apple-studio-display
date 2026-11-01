{
  pkgs ? import <nixpkgs> { },
  kernelPackages ? pkgs.linuxPackages,
}:
kernelPackages.callPackage ./nix/package.nix { }
