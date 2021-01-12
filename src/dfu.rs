use cortex_m_rt::{pre_init};

/// RAM location used to store DFU trigger message
const DFU_MSG_ADDR: usize = 0x2001BC00;

/// DFU trigger message 
const DFU_TRIG_MSG: usize = 0xDECAFBAD;

/// Set DFU trigger message
pub unsafe fn trig_dfu() {
    let dfu_msg_addr = DFU_MSG_ADDR as *mut usize;
    *dfu_msg_addr = DFU_TRIG_MSG;
}

/// Called by reset handler in lib.rs immediately after reset, checks if booting into dfu is needed
#[pre_init]
unsafe fn __pre_init() {

    let dfu_msg_addr = DFU_MSG_ADDR as *mut usize;
    
    // Check DFU trigger message
    if *dfu_msg_addr == DFU_TRIG_MSG{

        // Reset message
        *dfu_msg_addr = 0x00000000;

        // Enable system config controller clock
        const RCC_APB2ENR: *mut u32 = 0xE000_ED88 as *mut u32;
        const RCC_APB2ENR_ENABLE_SYSCFG_CLOCK: u32 = 0x00004000;

        core::ptr::write_volatile(
            RCC_APB2ENR,
            *RCC_APB2ENR | RCC_APB2ENR_ENABLE_SYSCFG_CLOCK,
        );

        // Bypass BOOT pins and remap bootloader to 0x00000000
        const SYSCFG_MEMRMP: *mut u32 = 0x40013800 as *mut u32;
        const SYSCFG_MEMRMP_MAP_ROM: u32 = 0x00000001;

        core::ptr::write_volatile(
            SYSCFG_MEMRMP,
            *SYSCFG_MEMRMP | SYSCFG_MEMRMP_MAP_ROM,
        );

        // Set stack pointer to bootloader location
        asm!("LDR R0, =0x1FFF0000");
        asm!("LDR SP,[R0, #0]");

        // Jump to bootloader
        asm!("LDR R0,[R0, #4]");
        asm!("BX R0");
    }

}