//
// Stub file for when acquiring build-time information fails
//
#[doc = r#"The Continuous Integration platform detected during compilation."#]
#[allow(dead_code)]
pub const CI_PLATFORM: Option<&str> = None;
#[doc = r#"The full version."#]
#[allow(dead_code)]
pub const PKG_VERSION: &str = r"";
#[doc = r#"The major version."#]
#[allow(dead_code)]
pub const PKG_VERSION_MAJOR: &str = r"";
#[doc = r#"The minor version."#]
#[allow(dead_code)]
pub const PKG_VERSION_MINOR: &str = r"";
#[doc = r#"The patch version."#]
#[allow(dead_code)]
pub const PKG_VERSION_PATCH: &str = r"";
#[doc = r#"The pre-release version."#]
#[allow(dead_code)]
pub const PKG_VERSION_PRE: &str = r"";
#[doc = r#"A colon-separated list of authors."#]
#[allow(dead_code)]
pub const PKG_AUTHORS: &str = r"";
#[doc = r#"The name of the package."#]
#[allow(dead_code)]
pub const PKG_NAME: &str = r"";
#[doc = r#"The description."#]
#[allow(dead_code)]
pub const PKG_DESCRIPTION: &str = r"";
#[doc = r#"The homepage."#]
#[allow(dead_code)]
pub const PKG_HOMEPAGE: &str = r"";
#[doc = r#"The license."#]
#[allow(dead_code)]
pub const PKG_LICENSE: &str = r"";
#[doc = r#"The source repository as advertised in Cargo.toml."#]
#[allow(dead_code)]
pub const PKG_REPOSITORY: &str = r"";
#[doc = r#"The target triple that was being compiled for."#]
#[allow(dead_code)]
pub const TARGET: &str = r"";
#[doc = r#"The host triple of the rust compiler."#]
#[allow(dead_code)]
pub const HOST: &str = r"";
#[doc = r#"`release` for release builds, `debug` for other builds."#]
#[allow(dead_code)]
pub const PROFILE: &str = r"";
#[doc = r#"The compiler that cargo resolved to use."#]
#[allow(dead_code)]
pub const RUSTC: &str = r"";
#[doc = r#"The documentation generator that cargo resolved to use."#]
#[allow(dead_code)]
pub const RUSTDOC: &str = r"";
#[doc = r#"Value of OPT_LEVEL for the profile used during compilation."#]
#[allow(dead_code)]
pub const OPT_LEVEL: &str = r"";
#[doc = r#"The parallelism that was specified during compilation."#]
#[allow(dead_code)]
pub const NUM_JOBS: u32 = 0;
#[doc = r#"Value of DEBUG for the profile used during compilation."#]
#[allow(dead_code)]
pub const DEBUG: bool = false;
#[doc = r#"The features that were enabled during compilation."#]
#[allow(dead_code)]
pub const FEATURES: [&str; 0] = [];
#[doc = r#"The features as a comma-separated string."#]
#[allow(dead_code)]
pub const FEATURES_STR: &str = r"";
#[doc = r#"The features as above, as lowercase strings."#]
#[allow(dead_code)]
pub const FEATURES_LOWERCASE: [&str; 0] = [];
#[doc = r#"The feature-string as above, from lowercase strings."#]
#[allow(dead_code)]
pub const FEATURES_LOWERCASE_STR: &str = r"";
#[doc = r#"The output of `rustc -V`"#]
#[allow(dead_code)]
pub const RUSTC_VERSION: &str = r"";
#[doc = r#"The output of `rustdoc -V`"#]
#[allow(dead_code)]
pub const RUSTDOC_VERSION: &str = r"";
#[doc = r#"The target architecture, given by `CARGO_CFG_TARGET_ARCH`."#]
#[allow(dead_code)]
pub const CFG_TARGET_ARCH: &str = r"";
#[doc = r#"The endianness, given by `CARGO_CFG_TARGET_ENDIAN`."#]
#[allow(dead_code)]
pub const CFG_ENDIAN: &str = r"";
#[doc = r#"The toolchain-environment, given by `CARGO_CFG_TARGET_ENV`."#]
#[allow(dead_code)]
pub const CFG_ENV: &str = r"";
#[doc = r#"The OS-family, given by `CARGO_CFG_TARGET_FAMILY`."#]
#[allow(dead_code)]
pub const CFG_FAMILY: &str = r"";
#[doc = r#"The operating system, given by `CARGO_CFG_TARGET_OS`."#]
#[allow(dead_code)]
pub const CFG_OS: &str = r"";
#[doc = r#"The pointer width, given by `CARGO_CFG_TARGET_POINTER_WIDTH`."#]
#[allow(dead_code)]
pub const CFG_POINTER_WIDTH: &str = r"";
#[doc = r#"If the crate was compiled from within a git-repository, `GIT_VERSION` contains HEAD's tag. The short commit id is used if HEAD is not tagged."#]
#[allow(dead_code)]
pub const GIT_VERSION: Option<&str> = None;
#[doc = r#"If the repository had dirty/staged files."#]
#[allow(dead_code)]
pub const GIT_DIRTY: Option<bool> = None;
#[doc = r#"If the crate was compiled from within a git-repository, `GIT_HEAD_REF` contains full name to the reference pointed to by HEAD (e.g.: `refs/heads/master`). If HEAD is detached or the branch name is not valid UTF-8 `None` will be stored."#]
#[allow(dead_code)]
pub const GIT_HEAD_REF: Option<&str> = None;
#[doc = r#"If the crate was compiled from within a git-repository, `GIT_COMMIT_HASH` contains HEAD's full commit SHA-1 hash."#]
#[allow(dead_code)]
pub const GIT_COMMIT_HASH: Option<&str> = None;
#[doc = r#"If the crate was compiled from within a git-repository, `GIT_COMMIT_HASH_SHORT` contains HEAD's short commit SHA-1 hash."#]
#[allow(dead_code)]
pub const GIT_COMMIT_HASH_SHORT: Option<&str> = None;
