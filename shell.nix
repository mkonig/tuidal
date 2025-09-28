{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  packages = with pkgs; [
    python313
    pipenv
    mpv
    mpvc
    libnotify
    socat
    rlwrap
    lefthook
    basedpyright
    hunspell
    hunspellDicts.en_US
    codespell
    python313Packages.mpv
  ];
}
