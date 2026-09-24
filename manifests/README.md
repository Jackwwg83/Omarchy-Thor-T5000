# Manifests

`l4t-r39.2.1.json` pins the 25 L4T packages the port repackages, one exact version each, with the
download URL, size and SHA-256 from NVIDIA's apt index. It is generated, not edited:

```sh
python3 scripts/l4t_manifest.py manifests/l4t-r39.2.1.json --release r39.2 --wanted manifests/l4t-wanted.tsv \
  https://repo.download.nvidia.com/jetson/common=cache/apt/Packages-common \
  https://repo.download.nvidia.com/jetson/som=cache/apt/Packages-som
```

`l4t-wanted.tsv` lists the packages and the versions installed on the JetPack 7.2.1 test machine.

The indexes were checked on 2026-09-24 before use: both `InRelease` files carry a good signature from
NVIDIA's Jetson repository key `13804AEEB181616F3B4964270D296FFB880FB004` (the key JetPack trusts in
`/etc/apt/trusted.gpg.d/jetson-ota-public.asc`), and each `Packages` file matches the SHA-256 listed there.

Boot-loader, partition, OTA and first-boot packages are refused by the tool itself
(`PROHIBITED_PACKAGES`); single prohibited files inside allowed packages are matched by `prohibited_path()`.
No NVIDIA payload is stored in this repository.
