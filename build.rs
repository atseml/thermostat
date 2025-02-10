use std::env;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

fn main() {
    // Put the linker script somewhere the linker can find it
    let out = &PathBuf::from(env::var_os("OUT_DIR").unwrap());
    File::create(out.join("memory.x"))
        .unwrap()
        .write_all(include_bytes!("memory.x"))
        .unwrap();
    println!("cargo:rustc-link-search={}", out.display());

    // Only re-run the build script when memory.x is changed,
    // instead of when any part of the source code changes.
    println!("cargo:rerun-if-changed=memory.x");

    // Embed build-time information, such as the Git hash.
    // Use stub file if acquiring fails.
    if built::write_built_file().is_err() {
        File::create(out.join("built.rs"))
            .unwrap()
            .write_all(include_bytes!("src/built.rs"))
            .unwrap();
    }
}
