use cortex_m_rt::{pre_init};

const DFU_MSG_ADDR: usize = 0x2001BC00;
const DFU_TRIG_MSG: usize = 0xDECAFBAD;

pub unsafe fn trig_dfu() {
    let dfu_msg_addr = DFU_MSG_ADDR as *mut usize;
    *dfu_msg_addr = DFU_TRIG_MSG;
}

#[pre_init]
#[no_mangle]
unsafe fn __pre_init() {

    let dfu_msg_addr = DFU_MSG_ADDR as *mut usize;
    
    if *dfu_msg_addr == DFU_TRIG_MSG{

        *dfu_msg_addr = 0x00000000;

        const RCC_APB2ENR: *mut u32 = 0xE000_ED88 as *mut u32;
        const RCC_APB2ENR_ENABLE_SYSCFG_CLOCK: u32 = 0x00004000;

        core::ptr::write_volatile(
            RCC_APB2ENR,
            *RCC_APB2ENR | RCC_APB2ENR_ENABLE_SYSCFG_CLOCK,
        );

        const SYSCFG_MEMRMP: *mut u32 = 0x40013800 as *mut u32;
        const SYSCFG_MEMRMP_MAP_ROM: u32 = 0x00000001;

        core::ptr::write_volatile(
            SYSCFG_MEMRMP,
            *SYSCFG_MEMRMP | SYSCFG_MEMRMP_MAP_ROM,
        );

        asm!("LDR R0, =0x1FFF0000");
        asm!("LDR SP,[R0, #0]");
        asm!("LDR R0,[R0, #4]");
        asm!("BX R0");
    }

}