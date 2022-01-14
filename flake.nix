{
    description = "Firmware for the Sinara 8451 Thermostat";

    inputs.nixpkgs.url = github:NixOS/nixpkgs/nixos-21.11;
    inputs.mozilla-overlay = { url = github:mozilla/nixpkgs-mozilla; flake = false; };

    outputs = { self, nixpkgs, mozilla-overlay }:
        let
            pkgs = import nixpkgs { system = "x86_64-linux"; overlays = [ (import mozilla-overlay) ]; };
            rustManifest = pkgs.fetchurl {
                url = "https://static.rust-lang.org/dist/2020-10-30/channel-rust-nightly.toml";
                sha256 = "0iygcwzh8s0lfdghj5809krvzifc1ii1wm4sd3qqn7s0rz1s14hi";
            };

            targets = [
                "thumbv7em-none-eabihf"
            ];
            rustChannelOfTargets = _channel: _date: targets:
                (pkgs.lib.rustLib.fromManifestFile rustManifest {
                    inherit (pkgs) stdenv lib fetchurl patchelf;
                    }).rust.override {
                    inherit targets;
                    extensions = ["rust-src"];
                };
            rust = rustChannelOfTargets "nightly" null targets;
            rustPlatform = pkgs.recurseIntoAttrs (pkgs.makeRustPlatform {
                rustc = rust;
                cargo = rust;
            });
            cargoSha256 = "0qb4s06jwgj3i9df6qq9gwcnyr3jq6dh4l5ygjghq5x1bmcqliix";
            buildStm32Firmware = { name, src, cargoDepsName ? name, patchPhase ? "", extraNativeBuildInputs ? [], checkPhase ? "", doCheck ? true, binaryName ? name, extraCargoBuildArgs ? "" }:
                rustPlatform.buildRustPackage rec {
                    inherit name cargoDepsName;
                    version = "0.0.0";

                    inherit src;
                    inherit cargoSha256;

                    inherit patchPhase;
                    nativeBuildInputs = [ pkgs.llvm ] ++ extraNativeBuildInputs;
                    buildPhase = ''
                    export CARGO_HOME=$(mktemp -d cargo-home.XXX)
                    cargo build --release --bin ${binaryName} ${extraCargoBuildArgs}
                    '';

                    inherit checkPhase doCheck;
                    # binaryName defaults to the `name` arg (i.e. the Rust package name);
                    # it is used as the Cargo binary filename
                    installPhase = ''
                    mkdir -p $out $out/nix-support
                    cp target/thumbv7em-none-eabihf/release/${binaryName} $out/${name}.elf
                    echo file binary-dist $out/${name}.elf >> $out/nix-support/hydra-build-products
                    llvm-objcopy -O binary target/thumbv7em-none-eabihf/release/${binaryName} $out/${name}.bin
                    echo file binary-dist $out/${name}.bin >> $out/nix-support/hydra-build-products
                    '';

                    dontFixup = true;
                };
        in {
            packages.x86_64-linux = rec {
                thermostat = buildStm32Firmware {
                    name = "thermostat";
                    src = self;
                    checkPhase = ''
                        cargo test --target=${pkgs.rust.toRustTarget pkgs.stdenv.targetPlatform};
                    '';
                };
            };
            devShell.x86_64-linux = pkgs.mkShell {
                name = "thermostat-dev-shell";
                buildInputs = with pkgs; [
                    rustPlatform.rust.rustc
                    rustPlatform.rust.cargo
                    gcc openocd dfu-util
                    ] ++ (with python3Packages; [
                        numpy matplotlib
                    ]);
            };
            defaultPackage.x86_64-linux = pkgs.python3.withPackages(ps: [ ]);
      };
}