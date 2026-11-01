{
  description = "Apple Studio Display kernel driver and desktop integration";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs, ... }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          driver = pkgs.linuxPackages.callPackage ./nix/package.nix { };
        in
        {
          default = driver;
          hid-apple-studio-display = driver;
          tools = pkgs.callPackage ./nix/tools.nix { };
        }
      );

      nixosModules.default = import ./nix/module.nix;

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          driver = self.packages.${system}.default;
          tools = self.packages.${system}.tools;
          module = import ./nix/module-check.nix {
            inherit nixpkgs pkgs;
            module = self.nixosModules.default;
          };
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
    };
}
