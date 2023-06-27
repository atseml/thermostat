{
  description = "Firmware for the Sinara 8451 Thermostat";

  inputs.nixpkgs.url = github:NixOS/nixpkgs/nixos-23.05;
  inputs.mozilla-overlay = { url = github:mozilla/nixpkgs-mozilla; flake = false; };

  outputs = { self, nixpkgs, mozilla-overlay }:
    let
      pkgs = import nixpkgs { system = "x86_64-linux"; overlays = [ (import mozilla-overlay) ]; };
      rustManifest = pkgs.fetchurl {
        url = "https://static.rust-lang.org/dist/2022-12-15/channel-rust-stable.toml";
        hash = "sha256-S7epLlflwt0d1GZP44u5Xosgf6dRrmr8xxC+Ml2Pq7c=";
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
      rust = rustChannelOfTargets "stable" null targets;
      rustPlatform = pkgs.recurseIntoAttrs (pkgs.makeRustPlatform {
        rustc = rust;
        cargo = rust;
      });
      thermostat = rustPlatform.buildRustPackage {
        name = "thermostat";
        version = "0.0.0";

        src = self;
        cargoLock = { 
          lockFile = ./Cargo.lock;
          outputHashes = {
            "stm32-eth-0.2.0" = "sha256-48RpZgagUqgVeKm7GXdk3Oo0v19ScF9Uby0nTFlve2o=";
          };
        };

        nativeBuildInputs = [ pkgs.llvm ];

        buildPhase = ''
          cargo build --release --bin thermostat
        '';

        installPhase = ''
          mkdir -p $out $out/nix-support
          cp target/thumbv7em-none-eabihf/release/thermostat $out/thermostat.elf
          echo file binary-dist $out/thermostat.elf >> $out/nix-support/hydra-build-products
          llvm-objcopy -O binary target/thumbv7em-none-eabihf/release/thermostat $out/thermostat.bin
          echo file binary-dist $out/thermostat.bin >> $out/nix-support/hydra-build-products
        '';

        dontFixup = true;
      };

      qasync = pkgs.python3Packages.buildPythonPackage rec {
        pname = "qasync";
        version = "0.27.1";
        format = "pyproject";
        src = pkgs.fetchPypi {
          inherit pname version;
          sha256 = "sha256-jcdo/R7l3hBEx8MF7M8tOdJNh4A+pxGJ1AJPtHX0mF8=";
        };
        buildInputs = [ pkgs.python3Packages.poetry-core ];
        propagatedBuildInputs = [ pkgs.python3Packages.pyqt6 ];
      };

      thermostat_gui = pkgs.python3Packages.buildPythonPackage {
        pname = "thermostat_gui";
        version = "0.0.0";
        src = "${self}/pytec";

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook ];
        propagatedBuildInputs = [ pkgs.qt6.qtbase ] ++ (with pkgs.python3Packages; [ pyqtgraph pyqt6 qasync ]);

        dontWrapQtApps = true;
        postFixup = ''
          wrapQtApp "$out/bin/tec_qt"
        '';
      };
    in {
      packages.x86_64-linux = {
        inherit thermostat thermostat_gui;
      };

      apps.x86_64-linux.thermostat_gui = {
        type = "app";
        program = "${self.packages.x86_64-linux.thermostat_gui}/bin/tec_qt";
      };

      hydraJobs = {
        inherit thermostat;
      };

      devShell.x86_64-linux = pkgs.mkShell {
        name = "thermostat-dev-shell";
        buildInputs = with pkgs; [
          rust openocd dfu-util
          ] ++ (with python3Packages; [
            numpy matplotlib pyqtgraph setuptools pyqt6 qasync
          ]);
      };
      defaultPackage.x86_64-linux = thermostat;
    };
}