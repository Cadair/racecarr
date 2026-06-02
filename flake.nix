{
  description = "Racecarr - F1 race tracking and downloading service";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
  };

  outputs = inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];

      perSystem = { config, self', inputs', pkgs, system, ... }:
        let
          python = pkgs.python313;

          # Frontend build
          frontend = pkgs.buildNpmPackage {
            pname = "racecarr-frontend";
            version = "0.5.0-beta";
            src = ./frontend;

            npmDepsHash = "sha256-MW4zOlyi9C4PFemLV1eCVr4Vd4NcXzuhimQ9AWcGUyw=";

            buildPhase = ''
              runHook preBuild
              npm run build
              runHook postBuild
            '';

            installPhase = ''
              runHook preInstall
              mkdir -p $out
              cp -r dist/* $out/
              cp package.json $out/
              runHook postInstall
            '';
          };

          # Python dependencies
          pythonWithDeps = python.withPackages (ps: with ps; [
            fastapi
            uvicorn
            sqlalchemy
            alembic
            pydantic
            pydantic-settings
            httpx
            apscheduler
            python-dotenv
            loguru
            itsdangerous
            passlib
            bcrypt
            apprise
          ]);

          # Backend package
          racecarr = pkgs.stdenv.mkDerivation {
            pname = "racecarr";
            version = "0.5.0-beta";
            src = ./.;

            nativeBuildInputs = [ pkgs.makeWrapper ];

            buildInputs = [ pythonWithDeps ];

            dontBuild = true;

            installPhase = ''
              runHook preInstall

              mkdir -p $out/lib/racecarr
              mkdir -p $out/bin

              # Copy backend source
              cp -r backend $out/lib/racecarr/

              # Copy frontend static assets
              mkdir -p $out/lib/racecarr/backend/app/static
              cp -r ${frontend}/* $out/lib/racecarr/backend/app/static/ || true

              # Keep frontend package.json for About page
              mkdir -p $out/lib/racecarr/frontend
              cp ${frontend}/package.json $out/lib/racecarr/frontend/package.json

              # Create wrapper script
              makeWrapper ${pythonWithDeps}/bin/uvicorn $out/bin/racecarr \
                --add-flags "backend.app.main:app" \
                --add-flags "--host 0.0.0.0" \
                --chdir $out/lib/racecarr \
                --prefix PYTHONPATH : $out/lib/racecarr

              runHook postInstall
            '';

            meta = with pkgs.lib; {
              description = "F1 race tracking and downloading service";
              homepage = "https://github.com/mrgibbage/racecarr";
              license = licenses.mit;
              maintainers = [ ];
              platforms = platforms.unix;
            };
          };

        in
        {
          packages = {
            inherit racecarr frontend;
            default = racecarr;
          };

          devShells.default = pkgs.mkShell {
            packages = [
              pythonWithDeps
              pkgs.nodejs_20
              pkgs.nodePackages.npm
            ];
          };
        };

      flake = {
        nixosModules.default = { config, lib, pkgs, ... }:
          let
            cfg = config.services.racecarr;
          in
          {
            options.services.racecarr = {
              enable = lib.mkEnableOption "Racecarr F1 race tracking service";

              package = lib.mkOption {
                type = lib.types.package;
                default = inputs.self.packages.${pkgs.system}.racecarr;
                defaultText = lib.literalExpression "inputs.racecarr.packages.\${pkgs.system}.racecarr";
                description = "The racecarr package to use.";
              };

              port = lib.mkOption {
                type = lib.types.port;
                default = 8080;
                description = "Port to listen on.";
              };

              dataDir = lib.mkOption {
                type = lib.types.path;
                default = "/var/lib/racecarr";
                description = "Directory for SQLite database and logs.";
              };

              user = lib.mkOption {
                type = lib.types.str;
                default = "racecarr";
                description = "User account under which racecarr runs.";
              };

              group = lib.mkOption {
                type = lib.types.str;
                default = "racecarr";
                description = "Group under which racecarr runs.";
              };

              openFirewall = lib.mkOption {
                type = lib.types.bool;
                default = false;
                description = "Whether to open the firewall for the racecarr port.";
              };

              environment = lib.mkOption {
                type = lib.types.attrsOf lib.types.str;
                default = { };
                example = lib.literalExpression ''
                  {
                    LOG_LEVEL = "DEBUG";
                    AUTH_SECRET = "my-secret-key";
                  }
                '';
                description = "Additional environment variables for the racecarr service.";
              };
            };

            config = lib.mkIf cfg.enable {
              users.users = lib.mkIf (cfg.user == "racecarr") {
                racecarr = {
                  isSystemUser = true;
                  group = cfg.group;
                  home = cfg.dataDir;
                  description = "Racecarr service user";
                };
              };

              users.groups = lib.mkIf (cfg.group == "racecarr") {
                racecarr = { };
              };

              systemd.services.racecarr = {
                description = "Racecarr F1 race tracking service";
                wantedBy = [ "multi-user.target" ];
                after = [ "network.target" ];

                environment = {
                  SQLITE_PATH = "${cfg.dataDir}/data.db";
                  LOG_PATH = "${cfg.dataDir}/app.log";
                } // cfg.environment;

                serviceConfig = {
                  Type = "simple";
                  User = cfg.user;
                  Group = cfg.group;
                  ExecStart = "${cfg.package}/bin/racecarr --port ${toString cfg.port}";
                  Restart = "on-failure";
                  RestartSec = 5;

                  # Hardening
                  NoNewPrivileges = true;
                  PrivateTmp = true;
                  ProtectSystem = "strict";
                  ProtectHome = true;
                  ReadWritePaths = [ cfg.dataDir ];

                  # State directory
                  StateDirectory = lib.mkIf (cfg.dataDir == "/var/lib/racecarr") "racecarr";
                  StateDirectoryMode = "0750";
                };

                preStart = lib.mkIf (cfg.dataDir != "/var/lib/racecarr") ''
                  mkdir -p ${cfg.dataDir}
                  chown ${cfg.user}:${cfg.group} ${cfg.dataDir}
                  chmod 0750 ${cfg.dataDir}
                '';
              };

              networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
            };
          };
      };
    };
}
