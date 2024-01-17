use crate::command_handler::JsonBuffer;
use serde::Serialize;

mod built_info {
    include!(concat!(env!("OUT_DIR"), "/built.rs"));
}

#[derive(Serialize)]
pub struct FirmwareSummary {
    git_commit_hash: Option<&'static str>,
    git_dirty: Option<bool>,
}

impl FirmwareSummary {
    pub const fn get() -> FirmwareSummary {
        FirmwareSummary {
            git_commit_hash: built_info::GIT_COMMIT_HASH,
            git_dirty: built_info::GIT_DIRTY,
        }
    }
}

pub fn summary() -> Result<JsonBuffer, serde_json_core::ser::Error> {
    serde_json_core::to_vec(&FirmwareSummary::get())
}
