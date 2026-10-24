//! Keep the core and bundled workers inside the desktop manager's lifetime.
use std::process::Child;

#[cfg(windows)]
pub struct ProcessTree(std::os::windows::io::OwnedHandle);
#[cfg(not(windows))]
pub struct ProcessTree;

impl ProcessTree {
    #[cfg(windows)]
    pub fn attach(child: &Child) -> Result<Self, String> {
        use std::{mem::{size_of, zeroed}, os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle}};
        use windows_sys::Win32::System::JobObjects::{
            AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
            SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        };
        unsafe {
            let raw = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if raw.is_null() { return Err(format!("Cannot create manager job: {}", std::io::Error::last_os_error())); }
            let handle = OwnedHandle::from_raw_handle(raw);
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(handle.as_raw_handle(), JobObjectExtendedLimitInformation,
                (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(), size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32) == 0
                || AssignProcessToJobObject(handle.as_raw_handle(), child.as_raw_handle()) == 0 {
                return Err(format!("Cannot protect manager process tree: {}", std::io::Error::last_os_error()));
            }
            Ok(Self(handle))
        }
    }

    #[cfg(not(windows))]
    pub fn attach(_child: &Child) -> Result<Self, String> { Ok(Self) }

    pub fn terminate(&self) {
        #[cfg(windows)] {
            use std::os::windows::io::AsRawHandle;
            unsafe { windows_sys::Win32::System::JobObjects::TerminateJobObject(self.0.as_raw_handle(), 1); }
        }
    }
}
