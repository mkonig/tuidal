{ pkgs ? import <nixpkgs> { } }:

let
  # =============================================================================
  # Configuration - modify these to enable/disable features
  # =============================================================================
  enabled = [ python ];

  createNvimLua = true;

  extraPackages = [ ];

  extraNvimConfig = ''
  '';
  # =============================================================================

  lib = pkgs.lib;

  # ==== LANGUAGES ====
  python = {
    packages = [
      pkgs.python313
      pkgs.pdm
      pkgs.basedpyright
      pkgs.black
      pkgs.isort
      pkgs.python313Packages.flake8
      pkgs.python313Packages.pylint
      pkgs.python313Packages.bandit
      pkgs.python313Packages.pydocstyle
      pkgs.python313Packages.docformatter
      pkgs.codespell
      pkgs.mpv
      pkgs.libnotify
      pkgs.lefthook
      pkgs.hunspell
      pkgs.cocogitto
      pkgs.hunspellDicts.en_US
      pkgs.python313Packages.mpv
      pkgs.python313Packages.pyspelling
      pkgs.python313Packages.mdformat
      pkgs.autoflake
      pkgs.markdownlint-cli2
    ];
    linters = ''
      python = { "codespell", "bandit", "flake8", "pylint", "pydocstyle" },
    '';
    formatters = ''
      python = { "isort", "docformatter", "black" },
    '';
    lsp = ''
      basedpyright = {
          settings = {
            basedpyright = {
              disableLanguageServices = false,
              disableOrganizeImports = true,
              analysis = {
                autoSearchPaths = true,
                useLibraryCodeForTypes = true,
                diagnosticMode = "openFilesOnly",
                inlayHints = {
                  variableTypes = false,
                  callArgumentNames = false,
                  functionReturnTypes = false,
                  genericTypes = false,
                },
              },
            },
          },
        }
      vim.lsp.config.basedpyright = basedpyright
      vim.lsp.enable('basedpyright')
    '';
    formatterSetup = "";
    hook = "";
  };
  # ==== END LANGUAGES ====

  packages = lib.flatten (map (x: x.packages) enabled) ++ extraPackages;
  linters = lib.concatStrings (map (x: x.linters) enabled);
  formatters = lib.concatStrings (map (x: x.formatters) enabled);
  formatterSetups = lib.concatStrings (map (x: x.formatterSetup) enabled);
  lspConfigs = lib.concatStrings (map (x: x.lsp) enabled);
  setupHook = lib.concatStrings (map (x: x.hook) enabled);

  nvimConfig = ''
    vim.o.exrc = false

    ${lspConfigs}
    local lint = require("lint")
    lint.linters_by_ft = {
    ${linters}}
    ${formatterSetups}
    require("conform").formatters_by_ft = {
    ${formatters}}
    ${extraNvimConfig}
  '';

  nvimHook = lib.optionalString createNvimLua ''
    hash="${builtins.hashString "sha256" nvimConfig}"
    if [ ! -f .nvim.lua ] || ! grep -q "$hash" .nvim.lua; then
      cat > .nvim.lua << 'NVIM_EOF'
    -- hash: ${builtins.hashString "sha256" nvimConfig}
    ${nvimConfig}
    NVIM_EOF
      echo "Created .nvim.lua"
    fi
  '';

  syncHook = ''
    export BETTER_EXCEPTIONS=1
    if command -v project_shell &> /dev/null; then
      project_shell --sync
    fi
  '';
in
pkgs.mkShell {
  inherit packages;
  shellHook = syncHook + setupHook + nvimHook;
}
