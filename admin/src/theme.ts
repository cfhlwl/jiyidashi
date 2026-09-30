import type { ThemeConfig } from 'antd'

export const adminTheme: ThemeConfig = {
  token: {
    colorPrimary: '#2457d6',
    colorInfo: '#2457d6',
    colorSuccess: '#217a4b',
    colorWarning: '#a56012',
    colorError: '#b42318',
    colorText: '#172033',
    colorTextSecondary: '#5b6578',
    colorBorder: '#d9dee8',
    colorBgBase: '#f4f6f9',
    colorBgContainer: '#ffffff',
    borderRadius: 8,
    borderRadiusLG: 10,
    fontFamily:
      '"Inter","PingFang SC","Microsoft YaHei","Noto Sans CJK SC",system-ui,sans-serif',
    fontSize: 14,
    controlHeight: 36,
    controlHeightLG: 40,
    lineWidth: 1,
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#101827',
      bodyBg: '#f4f6f9',
    },
    Menu: {
      darkItemBg: '#101827',
      darkItemSelectedBg: '#1d3260',
      darkItemHoverBg: '#18243a',
      itemBorderRadius: 6,
    },
    Table: {
      headerBg: '#f7f8fa',
      headerColor: '#384152',
      rowHoverBg: '#f8faff',
      cellPaddingBlock: 12,
      cellPaddingInline: 14,
    },
    Card: {
      paddingLG: 20,
      headerHeight: 48,
    },
    Button: {
      borderRadius: 7,
    },
    Modal: {
      borderRadiusLG: 10,
    },
  },
}
