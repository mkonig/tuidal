{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  PIPENV_VENV_IN_PROJECT = true;
  shellHook = ''
    export PYTHONPATH=$PYTHONPATH:$(fd -I -td site-packages $(pipenv --venv))
  '';
  packages = with pkgs; [
    python313
    pipenv
    mpv
    libnotify
    lefthook
    basedpyright
    hunspell
    hunspellDicts.en_US
    codespell
    python313Packages.mpv
  ];
}
